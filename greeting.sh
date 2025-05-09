#!/bin/bash

# Explicitly print prompt to stdout without a newline
echo -n "What is your name? "

# Use plain read to get input
read name


# Print the greeting
echo "Hello, $name."

