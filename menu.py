import sys
import os
import yaml
import subprocess
import tkinter as tk
from tkinter import ttk, scrolledtext
from PIL import Image, ImageTk
import threading
import queue

class OutputTerminal(scrolledtext.ScrolledText):
    """Custom ScrolledText that formats and displays terminal output"""
    def __init__(self, parent=None, **kwargs):
        super().__init__(parent, **kwargs)
        self.configure(
            wrap=tk.WORD,
            font=('Courier', 10),
            bg='#f0f0f0',
            relief=tk.FLAT,
            padx=10,
            pady=10
        )
        self.tag_configure('error', foreground='#cc0000')
        self.tag_configure('normal', foreground='#333333')
        self.configure(state='disabled')
        
    def append_output(self, text, error=False):
        """Append text to the terminal with appropriate formatting"""
        self.configure(state='normal')
        tag = 'error' if error else 'normal'
        
        # Handle carriage returns
        if '\r' in text and not text.endswith('\r'):
            lines = text.split('\r')
            # Delete the last line
            self.delete('end-2c linestart', 'end-1c')
            self.insert('end', lines[-1], tag)
        else:
            self.insert('end', text, tag)
        
        self.see('end')
        self.configure(state='disabled')

class ProcessManager:
    """Manages command execution and handles output"""
    def __init__(self, output_callback=None, finished_callback=None, started_callback=None):
        self.process = None
        self.output_callback = output_callback
        self.finished_callback = finished_callback
        self.started_callback = started_callback
        self.output_queue = queue.Queue()
        self.running = False
        
    def execute_command(self, command):
        """Execute a shell command"""
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.process.wait()
        
        self.process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        self.running = True
        if self.started_callback:
            self.started_callback()
            
        # Start output monitoring threads
        threading.Thread(target=self._monitor_output, args=(self.process.stdout, False), daemon=True).start()
        threading.Thread(target=self._monitor_output, args=(self.process.stderr, True), daemon=True).start()
        threading.Thread(target=self._monitor_process, daemon=True).start()
    
    def _monitor_output(self, pipe, is_error):
        """Monitor process output and put it in the queue"""
        for line in iter(pipe.readline, ''):
            self.output_queue.put((line, is_error))
        pipe.close()
    
    def _monitor_process(self):
        """Monitor process completion"""
        self.process.wait()
        self.running = False
        if self.finished_callback:
            self.finished_callback(self.process.returncode)
    
    def send_input(self, text):
        """Send input to the running process"""
        if self.process and self.process.poll() is None:
            if not text.endswith('\n'):
                text += '\n'
            self.process.stdin.write(text)
            self.process.stdin.flush()
            return True
        return False
    
    def is_running(self):
        """Check if process is running"""
        return self.running

class OutputWindow(tk.Toplevel):
    """Detachable window for command output"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.title("Command Output")
        self.geometry("600x400")
        
        # Create main frame
        main_frame = ttk.Frame(self)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Output terminal
        self.output_terminal = OutputTerminal(main_frame)
        self.output_terminal.pack(fill=tk.BOTH, expand=True)
        
        # Input frame
        input_frame = ttk.Frame(main_frame)
        input_frame.pack(fill=tk.X, pady=(5, 0))
        
        ttk.Label(input_frame, text="Input:").pack(side=tk.LEFT, padx=(0, 5))
        
        self.input_field = ttk.Entry(input_frame)
        self.input_field.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.input_field.bind('<Return>', lambda e: self.send_input())
        
        self.send_button = ttk.Button(input_frame, text="Send", command=self.send_input)
        self.send_button.pack(side=tk.LEFT, padx=5)
        
        # Button frame
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(5, 0))
        
        self.clear_button = ttk.Button(button_frame, text="Clear Output", command=self.output_terminal.delete(1.0, tk.END))
        self.clear_button.pack(side=tk.LEFT)
        
        self.close_button = ttk.Button(button_frame, text="Close", command=self.hide)
        self.close_button.pack(side=tk.RIGHT)
        
        self.input_callback = None
    
    def send_input(self):
        """Send input from the input field"""
        text = self.input_field.get()
        if text and self.input_callback:
            self.input_callback(text)
            self.output_terminal.append_output(f"> {text}\n", False)
            self.input_field.delete(0, tk.END)
    
    def set_input_enabled(self, enabled):
        """Enable or disable the input controls"""
        state = 'normal' if enabled else 'disabled'
        self.input_field.configure(state=state)
        self.send_button.configure(state=state)

class MenuApplication(tk.Tk):
    def __init__(self, config_file):
        super().__init__()
        self.config = self.load_config(config_file)
        self.init_ui()
        
        # Create process manager
        self.process_manager = ProcessManager(
            output_callback=self.update_output,
            finished_callback=self.on_process_finished,
            started_callback=self.on_process_started
        )
        
        # Create detachable output window
        self.output_window = OutputWindow(self)
        self.output_window.input_callback = self.send_process_input
        
        # Start output processing
        self.after(100, self.process_output_queue)
    
    def load_config(self, config_file):
        """Load configuration from YAML file"""
        try:
            with open(config_file, 'r') as file:
                return yaml.safe_load(file)
        except Exception as e:
            print(f"Error loading config file: {e}")
            return {}
    
    def init_ui(self):
        """Initialize the user interface"""
        # Set window title
        menu_title = self.config.get('menu_title', 'Menu Application')
        self.title(menu_title)
        
        # Set window icon
        icon_path = self.config.get('icon', '')
        if icon_path and os.path.exists(icon_path):
            self.iconphoto(True, tk.PhotoImage(file=icon_path))
        
        # Main frame
        main_frame = ttk.Frame(self, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Logo at the top
        logo_path = self.config.get('logo', '')
        if logo_path and os.path.exists(logo_path):
            try:
                logo_size = self.config.get('logo_size', '300x100')
                width, height = map(int, logo_size.split('x'))
            except (ValueError, AttributeError):
                width, height = 300, 100
            
            logo_image = Image.open(logo_path)
            logo_image = logo_image.resize((width, height), Image.Resampling.LANCZOS)
            self.logo_photo = ImageTk.PhotoImage(logo_image)
            
            logo_label = ttk.Label(main_frame, image=self.logo_photo)
            logo_label.pack(pady=(0, 20))
        
        # Create menu buttons
        self.create_menu_buttons(main_frame)
        
        # Set window size
        self.geometry(f"{max(500, width + 100)}x600")
    
    def create_menu_buttons(self, parent):
        """Create menu buttons from config"""
        menu_items = self.config.get('menu_items', [])
        
        for item in menu_items:
            if item.get('type') == 'separator':
                ttk.Separator(parent, orient='horizontal').pack(fill=tk.X, pady=10)
            else:
                btn = ttk.Button(
                    parent,
                    text=item.get('label', ''),
                    command=lambda cmd=item.get('command'): self.execute_command(cmd)
                )
                btn.pack(fill=tk.X, pady=2)
    
    def execute_command(self, command):
        """Execute a command and show output window"""
        if command:
            self.process_manager.execute_command(command)
            self.output_window.deiconify()
    
    def update_output(self, text, is_error):
        """Update output in the terminal"""
        self.output_window.output_terminal.append_output(text, is_error)
    
    def on_process_started(self):
        """Handle process start"""
        self.output_window.set_input_enabled(True)
    
    def on_process_finished(self, exit_code):
        """Handle process completion"""
        self.output_window.set_input_enabled(False)
    
    def send_process_input(self, text):
        """Send input to the running process"""
        self.process_manager.send_input(text)
    
    def process_output_queue(self):
        """Process queued output from the process manager"""
        try:
            while True:
                text, is_error = self.process_manager.output_queue.get_nowait()
                self.update_output(text, is_error)
        except queue.Empty:
            pass
        finally:
            self.after(100, self.process_output_queue)

if __name__ == '__main__':
    config_file = 'menu_config.yaml'
    app = MenuApplication(config_file)
    app.mainloop()