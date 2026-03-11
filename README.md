# Cardputer-Laptop-Monitor

this is the Python script that connects LibreHardwareMonitor to an M5Stack Cardputer to display real-time PC hardware stats like CPU, GPU, RAM usage, and temperatures.




Cardputer Laptop Monitor Setup Guide

This project allows an M5Stack Cardputer to display live hardware statistics from a computer such as CPU usage, GPU usage, RAM usage, and temperatures. It works by using LibreHardwareMonitor to read system sensor data and a Python script (monitor.py) to send that data over USB serial to the Cardputer.

1. Install LibreHardwareMonitor

Download LibreHardwareMonitor and extract it anywhere on your computer. Run LibreHardwareMonitor.exe and ensure the program is open before running the Python script. In the options menu, enable the Remote Web Server so the sensor data can be accessed. The monitor script reads the data from http://localhost:8085/data.json, which LibreHardwareMonitor provides when the web server is enabled.

2. Install Python Dependencies

Make sure Python is installed on your system. Then install the required libraries by running:

py -m pip install requests pyserial
py -m pip install psutil

These libraries allow the script to read hardware data and communicate with the Cardputer through the serial port.

3. Connect the Cardputer

Flash the Cardputer monitor firmware to your device and connect the Cardputer to your computer using USB. Identify the correct COM port (for example COM5) in your system’s device manager.

4. Run the Monitor Script

Open monitor.py and set the correct COM port if needed. Then run the script:

python monitor.py

The script will continuously collect system sensor data from LibreHardwareMonitor and transmit it to the Cardputer, where it will be displayed in real time with graphs and system statistics.
