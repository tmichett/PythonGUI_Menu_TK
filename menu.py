import sys
import os
import yaml
import subprocess
from PyQt5.QtWidgets import (QApplication, QMainWindow, QPushButton, QVBoxLayout, 
                            QWidget, QLabel, QTextEdit, QFrame, QStackedWidget,
                            QHBoxLayout, QGridLayout, QDialog, QSplitter, QLineEdit)
from PyQt5.QtGui import QIcon, QPixmap, QFont
from PyQt5.QtCore import Qt, QProcess, pyqtSignal, QObject

class OutputTerminal(QTextEdit):
    """Custom QTextEdit that formats and displays terminal output"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setStyleSheet("background-color: #f0f0f0; border-radius: 5px; padding: 10px; font-family: monospace;")
        self.document().setMaximumBlockCount(5000)  # Limit to prevent memory issues
    
    def append_output(self, text, error=False):
        """Append text to the terminal with appropriate formatting"""
        # Process text to handle newlines properly
        color = "#cc0000" if error else "#333333"
        
        # HTML escape the text to preserve formatting
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        
        # Replace newlines with HTML line breaks
        text = text.replace("\n", "<br>")
        
        # Ensure carriage returns are handled correctly (terminal-like behavior)
        if "\r" in text and not text.endswith("\r"):
            lines = text.split("\r")
            # Replace the last line in the document
            cursor = self.textCursor()
            cursor.movePosition(cursor.End)
            cursor.select(cursor.LineUnderCursor)
            cursor.removeSelectedText()
            cursor.insertHtml(f"<span style='color: {color};'>{lines[-1]}</span>")
        else:
            # Normal append for text without carriage returns
            self.append(f"<span style='color: {color};'>{text}</span>")
        
        # Scroll to bottom
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

class ProcessManager(QObject):
    """Manages command execution and emits output signals"""
    output_received = pyqtSignal(str, bool)  # text, is_error
    process_finished = pyqtSignal(int, QProcess.ExitStatus)  # exit code, exit status
    process_started = pyqtSignal()  # Signal when process starts
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QProcess()
        self.process.readyReadStandardOutput.connect(self.handle_stdout)
        self.process.readyReadStandardError.connect(self.handle_stderr)
        self.process.finished.connect(self.process_finished)
        self.process.started.connect(self.process_started)
    
    def execute_command(self, command):
        """Execute a shell command"""
        if self.process.state() == QProcess.Running:
            self.process.kill()
            self.process.waitForFinished()
        
        # Use bash for better terminal compatibility
        self.process.start('bash', ['-c', command])
    
    def handle_stdout(self):
        """Handle standard output data"""
        data = self.process.readAllStandardOutput().data().decode('utf-8', errors='replace')
        if data:
            self.output_received.emit(data, False)
    
    def handle_stderr(self):
        """Handle standard error data"""
        data = self.process.readAllStandardError().data().decode('utf-8', errors='replace')
        if data:
            self.output_received.emit(data, True)
    
    def send_input(self, text):
        """Send input to the running process"""
        if self.process.state() == QProcess.Running:
            # Add newline if not present
            if not text.endswith('\n'):
                text += '\n'
            self.process.write(text.encode('utf-8'))
            return True
        return False
    
    def is_running(self):
        """Check if process is running"""
        return self.process.state() == QProcess.Running

class OutputWindow(QDialog):
    """Detachable window for command output"""
    input_sent = pyqtSignal(str)  # Signal when user sends input
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Command Output")
        self.setMinimumSize(600, 400)
        
        layout = QVBoxLayout(self)
        
        # Output terminal
        self.output_terminal = OutputTerminal()
        layout.addWidget(self.output_terminal)
        
        # Add input field
        input_layout = QHBoxLayout()
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(5)
        
        input_label = QLabel("Input:")
        input_label.setFixedWidth(50)
        input_label.setStyleSheet("""
            QLabel {
                color: #333333;
                font-weight: bold;
                padding: 5px;
            }
        """)
        input_layout.addWidget(input_label)
        
        self.input_field = QLineEdit()
        self.input_field.setStyleSheet("""
            QLineEdit {
                background-color: white;
                color: #333333;
                border: 1px solid #ccc;
                border-radius: 3px;
                padding: 5px;
                font-family: monospace;
            }
            QLineEdit:disabled {
                background-color: #f0f0f0;
                color: #666666;
            }
        """)
        self.input_field.returnPressed.connect(self.send_input)
        input_layout.addWidget(self.input_field)
        
        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(self.send_input)
        self.send_button.setEnabled(False)  # Initially disabled
        input_layout.addWidget(self.send_button)
        
        layout.addLayout(input_layout)
        
        # Create buttons for the dialog
        button_layout = QHBoxLayout()
        
        # Clear button
        self.clear_button = QPushButton("Clear Output")
        self.clear_button.clicked.connect(self.output_terminal.clear)
        button_layout.addWidget(self.clear_button)
        
        # Close button
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.hide)
        button_layout.addWidget(self.close_button)
        
        layout.addLayout(button_layout)
    
    def send_input(self):
        """Send input from the input field"""
        text = self.input_field.text()
        if text:
            self.input_sent.emit(text)
            # Display the input in the terminal (user feedback)
            self.output_terminal.append_output(f"> {text}\n", False)
            self.input_field.clear()
    
    def set_input_enabled(self, enabled):
        """Enable or disable the input controls"""
        self.input_field.setEnabled(enabled)
        self.send_button.setEnabled(enabled)

class MenuApplication(QMainWindow):
    def __init__(self, config_file):
        super().__init__()
        self.config = self.load_config(config_file)
        self.init_ui()
        
        # Create process manager for command execution
        self.process_manager = ProcessManager()
        self.process_manager.output_received.connect(self.update_output)
        self.process_manager.process_finished.connect(self.on_process_finished)
        self.process_manager.process_started.connect(self.on_process_started)
        
        # Create detachable output window
        self.output_window = OutputWindow(self)
        self.output_window.input_sent.connect(self.send_process_input)
        
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
        self.setWindowTitle(menu_title)
        
        # Set window icon
        icon_path = self.config.get('icon', '')
        if icon_path and os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        # Main widget and layout
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # Default window width
        window_width = 500
        
        # Logo at the top
        logo_path = self.config.get('logo', '')
        if logo_path and os.path.exists(logo_path):
            logo_label = QLabel()
            pixmap = QPixmap(logo_path)
            
            # Check if logo_size is specified in the config
            logo_size = self.config.get('logo_size', '300x100')
            try:
                width, height = map(int, logo_size.split('x'))
                # Update window width to be at least 100px wider than logo
                window_width = max(window_width, width + 100)
            except (ValueError, AttributeError):
                # Default to 300x100 if parsing fails
                width, height = 300, 100
                window_width = max(window_width, width + 100)
                
            logo_label.setPixmap(pixmap.scaled(width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            logo_label.setAlignment(Qt.AlignCenter)
            main_layout.addWidget(logo_label)
            
            # Add some spacing after logo
            spacer = QWidget()
            spacer.setFixedHeight(20)
            main_layout.addWidget(spacer)
        
        # Title label
        title_label = QLabel(menu_title)
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)
        
        # Add help button in top right corner
        help_button = QPushButton("Help")
        help_button.setStyleSheet("""
            QPushButton {
                background-color: #5bc0de;
                color: white;
                border-radius: 3px;
                padding: 5px 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #46b8da;
            }
        """)
        help_button.setFixedWidth(80)
        help_button.setFixedHeight(30)
        
        # Get help command from config
        help_command = self.config.get('menu_help', '')
        if help_command:
            help_button.clicked.connect(lambda: self.execute_command(help_command))
        else:
            help_button.setEnabled(False)
        
        # Create a horizontal layout for the title and help button
        title_layout = QHBoxLayout()
        title_layout.addWidget(title_label)
        title_layout.addWidget(help_button)
        main_layout.addLayout(title_layout)
        
        # Create stacked widget for main content and submenus
        self.stacked_widget = QStackedWidget()
        main_layout.addWidget(self.stacked_widget)
        
        # Create main menu page with multi-column support
        main_menu_widget = QWidget()
        
        # Get number of columns from config (default to 1)
        num_columns = self.config.get('num_columns', 1)
        
        # Create layout based on number of columns
        if num_columns > 1:
            main_menu_layout = QGridLayout(main_menu_widget)
            main_menu_layout.setSpacing(10)
        else:
            main_menu_layout = QVBoxLayout(main_menu_widget)
            main_menu_layout.setSpacing(10)
        
        # Create the main menu page first
        self.stacked_widget.addWidget(main_menu_widget)
        
        # Add buttons for each separator
        menu_items = self.config.get('menu_items', [])
        
        # Track items in each column
        column_items = {i+1: 0 for i in range(num_columns)}
        
        for i, separator in enumerate(menu_items):
            separator_name = separator.get('name', f'Menu {i+1}')
            separator_button = QPushButton(separator_name)
            separator_button.setMinimumHeight(50)
            
            # Add tooltip if button_info is provided
            button_info = separator.get('button_info', '')
            if button_info:
                separator_button.setToolTip(button_info.strip())  # Strip whitespace
                separator_button.setToolTipDuration(5000)  # Show for 5 seconds
            
            # Style the button
            separator_button.setStyleSheet("""
                QPushButton {
                    background-color: #4a86e8;
                    color: white;
                    border-radius: 5px;
                    font-size: 14px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #3d76d1;
                }
                QPushButton:pressed {
                    background-color: #2c5aa0;
                }
            """)
            
            # Create submenu page for this separator
            submenu_page = self.create_submenu_page(separator)
            page_index = self.stacked_widget.addWidget(submenu_page)
            
            # Connect button to show its submenu
            separator_button.clicked.connect(lambda checked, idx=page_index: 
                                           self.stacked_widget.setCurrentIndex(idx))
            
            # Get column for this menu item (default to 1)
            column = separator.get('column', 1)
            
            # Ensure column is valid
            if column < 1 or column > num_columns:
                column = 1
                
            # Add button to the appropriate column
            if num_columns > 1:
                row = column_items[column]
                main_menu_layout.addWidget(separator_button, row, column-1)
                column_items[column] += 1
            else:
                main_menu_layout.addWidget(separator_button)
        
        # Add exit button at the bottom, spanning all columns if using grid layout
        exit_button = QPushButton("Exit Application")
        exit_button.setMinimumHeight(50)
        exit_button.setStyleSheet("""
            QPushButton {
                background-color: #e06666;
                color: white;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #cc5050;
            }
            QPushButton:pressed {
                background-color: #b94343;
            }
        """)
        exit_button.clicked.connect(self.close)
        
        if num_columns > 1:
            # Add some empty space
            for col in range(num_columns):
                main_menu_layout.setColumnStretch(col, 1)
                
            # Add spacer rows
            max_rows = max(column_items.values()) if column_items else 0
            spacer_row = QWidget()
            main_menu_layout.addWidget(spacer_row, max_rows, 0, 1, num_columns)
            main_menu_layout.setRowStretch(max_rows, 1)
            
            # Add exit button spanning all columns
            main_menu_layout.addWidget(exit_button, max_rows + 1, 0, 1, num_columns)
        else:
            main_menu_layout.addStretch()
            main_menu_layout.addWidget(exit_button)
        
        # Create bottom frame for output area with title and controls
        output_frame = QFrame()
        output_frame.setFrameShape(QFrame.StyledPanel)
        output_frame.setStyleSheet("background-color: #f8f8f8; border-radius: 5px;")
        output_layout = QVBoxLayout(output_frame)
        
        # Output header with title and detach button
        output_header = QWidget()
        header_layout = QHBoxLayout(output_header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        
        output_title = QLabel("Command Output:")
        output_title.setFont(QFont("", 10, QFont.Bold))
        header_layout.addWidget(output_title)
        
        header_layout.addStretch()
        
        # Add detach button
        detach_button = QPushButton("Detach Output")
        detach_button.setStyleSheet("""
            QPushButton {
                background-color: #f0ad4e;
                color: white;
                border-radius: 3px;
                padding: 5px 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #ec971f;
            }
        """)
        detach_button.clicked.connect(self.detach_output_window)
        header_layout.addWidget(detach_button)
        
        # Add clear button
        clear_button = QPushButton("Clear")
        clear_button.setStyleSheet("""
            QPushButton {
                background-color: #d9534f;
                color: white;
                border-radius: 3px;
                padding: 5px 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #c9302c;
            }
        """)
        clear_button.clicked.connect(self.clear_output)
        header_layout.addWidget(clear_button)
        
        output_layout.addWidget(output_header)
        
        # Output text area
        self.output_text = OutputTerminal()
        output_layout.addWidget(self.output_text)
        
        # Add input field to main window
        input_layout = QHBoxLayout()
        
        input_label = QLabel("Input:")
        input_label.setFixedWidth(50)
        input_label.setStyleSheet("""
            QLabel {
                color: #333333;
                font-weight: bold;
                padding: 5px;
            }
        """)
        input_layout.addWidget(input_label)
        
        self.input_field = QLineEdit()
        self.input_field.setStyleSheet("""
            QLineEdit {
                background-color: white;
                color: #333333;
                border: 1px solid #ccc;
                border-radius: 3px;
                padding: 5px;
                font-family: monospace;
            }
            QLineEdit:disabled {
                background-color: #f0f0f0;
                color: #666666;
            }
        """)
        self.input_field.returnPressed.connect(self.send_input)
        self.input_field.setEnabled(False)  # Initially disabled
        input_layout.addWidget(self.input_field)
        
        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(self.send_input)
        self.send_button.setEnabled(False)  # Initially disabled
        input_layout.addWidget(self.send_button)
        
        output_layout.addLayout(input_layout)
        
        main_layout.addWidget(output_frame)
        
        # Set the main widget
        self.setCentralWidget(main_widget)
        
        # Set window size based on logo width plus 100px margin
        # If we have multiple columns, increase the width further
        if num_columns > 1:
            window_width = max(window_width, 250 * num_columns + 100)
            
        self.resize(window_width, 900)
        self.setMinimumWidth(window_width)
        
        # Set initial page
        self.stacked_widget.setCurrentIndex(0)
    
    def create_submenu_page(self, separator):
        """Create a page for the submenu items with column support"""
        page_widget = QWidget()
        page_layout = QVBoxLayout(page_widget)
        page_layout.setSpacing(10)
        
        # Add title for the submenu with MUCH LARGER and BOLDER font
        submenu_title = QLabel(separator.get('name', 'Submenu'))
        title_font = QFont()
        title_font.setPointSize(24)  # Much larger font size
        title_font.setBold(True)
        title_font.setWeight(99)  # Maximum boldness (normal is 50, bold is 75)
        submenu_title.setFont(title_font)
        submenu_title.setAlignment(Qt.AlignCenter)
        
        # No color styling, just bold and large
        page_layout.addWidget(submenu_title)
        
        # Add some spacing after title
        spacer_after_title = QWidget()
        spacer_after_title.setFixedHeight(15)
        page_layout.addWidget(spacer_after_title)
        
        # Add a simple line separator
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        page_layout.addWidget(line)
        
        # Create widget for submenu buttons
        submenu_buttons_widget = QWidget()
        
        # Get number of columns for this submenu (default to 1)
        submenu_columns = separator.get('submenu_columns', 1)
        
        # Create layout based on number of columns
        if submenu_columns > 1:
            submenu_buttons_layout = QGridLayout(submenu_buttons_widget)
            submenu_buttons_layout.setSpacing(10)
        else:
            submenu_buttons_layout = QVBoxLayout(submenu_buttons_widget)
            submenu_buttons_layout.setSpacing(10)
        
        # Track items in each column
        column_items = {i+1: 0 for i in range(submenu_columns)}
        
        # Add buttons for each item in the submenu
        items = separator.get('items', [])
        for item in items:
            item_name = item.get('name', '')
            command = item.get('command', '')
            
            if item_name and command:
                item_button = QPushButton(item_name)
                item_button.setMinimumHeight(40)
                
                # Add tooltip if button_info is provided
                button_info = item.get('button_info', '')
                if button_info:
                    item_button.setToolTip(button_info.strip())  # Strip whitespace
                    item_button.setToolTipDuration(5000)  # Show for 5 seconds
                
                # Style the button - using blue style like main menu buttons
                item_button.setStyleSheet("""
                    QPushButton {
                        background-color: #4a86e8;
                        color: white;
                        border-radius: 5px;
                        font-size: 13px;
                        text-align: left;
                        padding-left: 15px;
                    }
                    QPushButton:hover {
                        background-color: #3d76d1;
                    }
                    QPushButton:pressed {
                        background-color: #2c5aa0;
                    }
                """)
                
                # Connect button to execute command
                item_button.clicked.connect(lambda checked, cmd=command: self.execute_command(cmd))
                
                # Get column for this item (default to 1)
                column = item.get('column', 1)
                
                # Ensure column is valid
                if column < 1 or column > submenu_columns:
                    column = 1
                
                # Add button to the appropriate column
                if submenu_columns > 1:
                    row = column_items[column]
                    submenu_buttons_layout.addWidget(item_button, row, column-1)
                    column_items[column] += 1
                else:
                    submenu_buttons_layout.addWidget(item_button)
        
        # Add column stretching if using grid layout
        if submenu_columns > 1:
            for col in range(submenu_columns):
                submenu_buttons_layout.setColumnStretch(col, 1)
        else:
            submenu_buttons_layout.addStretch()
            
        # Add the submenu buttons widget to the page layout
        page_layout.addWidget(submenu_buttons_widget)
        
        # Add spacing between buttons and back button
        page_layout.addStretch()
        
        # Add back button
        back_button = QPushButton("Back to Main Menu")
        back_button.setMinimumHeight(40)
        back_button.setStyleSheet("""
            QPushButton {
                background-color: #6aa84f;
                color: white;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #5d9745;
            }
            QPushButton:pressed {
                background-color: #4d7e3a;
            }
        """)
        # Direct connection to go back to main menu
        back_button.clicked.connect(self.go_back_to_main)
        page_layout.addWidget(back_button)
        
        return page_widget
    
    def go_back_to_main(self):
        """Go back to the main menu"""
        self.stacked_widget.setCurrentIndex(0)
    
    def execute_command(self, command):
        """Execute the command and show output in real-time"""
        # Clear output areas
        self.output_text.clear()
        self.output_window.output_terminal.clear()
        
        # Display command that is being executed
        cmd_display = f"Executing: {command}\n{'-' * 50}\n"
        self.output_text.append_output(cmd_display)
        self.output_window.output_terminal.append_output(cmd_display)
        
        # Execute the command
        self.process_manager.execute_command(command)
    
    def update_output(self, text, is_error):
        """Update both output terminals with new text"""
        self.output_text.append_output(text, is_error)
        self.output_window.output_terminal.append_output(text, is_error)
    
    def on_process_started(self):
        """Enable input fields when process starts"""
        self.input_field.setEnabled(True)
        self.send_button.setEnabled(True)
        self.output_window.set_input_enabled(True)
    
    def on_process_finished(self, exit_code, exit_status):
        """Handle process completion"""
        status_text = f"\n{'-' * 50}\nCommand finished with exit code: {exit_code}\n"
        if exit_code != 0:
            self.update_output(status_text, True)  # Show in red for non-zero exit
        else:
            self.update_output(status_text, False)
        
        # Disable input fields when process finishes
        self.input_field.setEnabled(False)
        self.send_button.setEnabled(False)
        self.output_window.set_input_enabled(False)
    
    def send_input(self):
        """Send input from the main window's input field"""
        text = self.input_field.text()
        if text and self.process_manager.is_running():
            # Display the input in both terminals (user feedback)
            self.output_text.append_output(f"> {text}\n", False)
            self.output_window.output_terminal.append_output(f"> {text}\n", False)
            
            # Send to process
            self.process_manager.send_input(text)
            self.input_field.clear()
    
    def send_process_input(self, text):
        """Send input from the detached output window"""
        if self.process_manager.is_running():
            # Send to process (the output window already shows the input)
            self.output_text.append_output(f"> {text}\n", False)  # Show in main window too
            self.process_manager.send_input(text)
    
    def detach_output_window(self):
        """Show the detached output window"""
        self.output_window.show()
        self.output_window.raise_()
        self.output_window.activateWindow()
        
        # Keep input field enabled state synchronized
        self.output_window.set_input_enabled(self.process_manager.is_running())
    
    def clear_output(self):
        """Clear both output terminals"""
        self.output_text.clear()
        self.output_window.output_terminal.clear()


if __name__ == "__main__":
    # Default config file path
    config_file = "config.yml"
    
    # Allow passing config file as argument
    if len(sys.argv) > 1:
        config_file = sys.argv[1]
    
    app = QApplication(sys.argv)
    window = MenuApplication(config_file)
    window.show()
    sys.exit(app.exec_())