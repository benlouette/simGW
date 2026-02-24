import tkinter as tk
from tkinter import scrolledtext
import serial
import threading
from datetime import datetime
from tkinter import filedialog
import time
import struct
from tkinter import ttk
from tkinter import Tk, filedialog
import os

# Define log level constants for easier identification of log types
ERROR = 1
INFO = 2
NMEA = 4
IO = 8
INTERRUPT = 16

# Mapping of log level values to their corresponding names
LOG_LEVELS = {
    ERROR: "ERROR",
    INFO: "INFO",
    NMEA: "NMEA",
    IO: "IO",
    INTERRUPT: "INTERRUPT"
}

# Custom widget class that provides multiple checkboxes for selecting log levels
class MultiCheckboxButton(tk.Frame):
    def __init__(self, parent, titles, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)

        # Create a list of BooleanVar objects to store the state of each checkbox
        self.vars = []
        for title in titles:
            var = tk.BooleanVar()
            checkbox = ttk.Checkbutton(self, text=title, variable=var)
            checkbox.pack(anchor=tk.W, padx=5, pady=2)  # Pack each checkbox vertically
            self.vars.append(var)

    def get_values(self):
        # Return a list of the current values (True/False) of each checkbox
        return [var.get() for var in self.vars]

def select_folder():
    # Hide the main window of Tkinter
    root = Tk()
    root.withdraw()

    # Open a dialog to select a folder
    folder_path = filedialog.askdirectory(title="Select Folder Containing EPO Files")
    
    # Close the Tkinter main window
    root.destroy()

    return folder_path

# Main application class for handling UART communication and UI elements
class UARTApp:
    def __init__(self, root, port, baudrate):
        self.root = root
        self.root.title("UART Communication")

        # Configure the root window's grid layout
        for i in range(4):
            self.root.columnconfigure(i, weight=1)

        # Initialize the serial connection
        self.serial_port = serial.Serial(port, baudrate, timeout=1)

        # Titles for the checkboxes representing different log levels
        self.titles = ["ERROR", "INFO", "NMEA", "IO", "INTERRUPT"]

        # Create a scrolled text area for displaying UART data
        self.text_area = scrolledtext.ScrolledText(root, wrap=tk.WORD, width=120, height=30)
        self.text_area.grid(column=0, row=0, columnspan=4, padx=10, pady=10, sticky="nsew")

        # Configure text tags for different log levels (colors)
        self.text_area.tag_configure("error", foreground="red")
        self.text_area.tag_configure("warning", foreground="blue")
        self.text_area.tag_configure("success", foreground="green")

        # Initialize various UI elements (buttons, entry fields)
        self.entry = tk.Entry(root, width=30)
        self.entryGeneral = tk.Entry(root, width=30)
        self.intern_command_button = tk.Button(root, text="intern_command", command=self.intern_command)
        self.general_command_button = tk.Button(root, text="general_command", command=self.general_command)
        self.log_button = tk.Button(root, text='Send "log GNSS"', command=self.send_log_command)
        self.toggle_button = tk.Button(root, text="Turn Off Display", command=self.toggle_display)
        self.print_status_button = tk.Button(root, text='print_status', command=self.print_status)

        # Initialize other buttons for sending various GNSS commands
        self.epo_get_statue_button = tk.Button(root, text='epo_get_statue', command=self.epo_get_statue)
        self.epo_erase_button = tk.Button(root, text='epo_erase', command=self.epo_erase)
        self.epo_load_from_buf_intern_button = tk.Button(root, text='epo_load_from_buf_intern', command=self.epo_load_from_buf_intern)
        self.start_up_module_button = tk.Button(root, text='start_up_module', command=self.start_up_module)
        self.shut_down_module_button = tk.Button(root, text='shut_down_module', command=self.shut_down_module)
        self.modem_query_epo_button = tk.Button(root, text='modem_query_epo', command=self.modem_query_epo)
        self.comm_connect_button = tk.Button(root, text='comm connect', command=self.comm_connect)
        self.task_run_app_98_button = tk.Button(root, text='task run app 98', command=self.task_run_app_98)
        self.simu_speed_button = tk.Button(root, text='simu_speed', command=self.simu_speed)
        self.task_run_app_97_button = tk.Button(root, text='task run app 97', command=self.task_run_app_97)
        self.set_rtc_reference_button = tk.Button(root, text='set_rtc_reference', command=self.set_rtc_reference)
        self.print_firmware_versio_button = tk.Button(root, text='print_firmware_versio', command=self.print_firmware_versio)
        self.disable_all_nmea_button = tk.Button(root, text='disable_all_nmea', command=self.disable_all_nmea)
        self.enable_nmea_button = tk.Button(root, text='enable_nmea', command=self.enable_nmea)
        self.subsys_full_cold_start_button = tk.Button(root, text='subsys_full_cold_start', command=self.subsys_full_cold_start)
        self.set_rtc_button = tk.Button(root, text='set_rtc', command=self.set_rtc)
        self.load_ephemeris_in_buf_button = tk.Button(root, text='load_ephemeris_in_buf', command=self.load_ephemeris_in_buf)
        self.set_configuration_button = tk.Button(root, text='set_configuration', command=self.set_configuration)
        self.query_configuration_button = tk.Button(root, text='query_configuration', command=self.query_configuration)
        self.wait_for_completion_button = tk.Button(root, text='wait_for_completion', command=self.wait_for_completion)
        self.erase_button = tk.Button(root, text="Erase Log", command=self.erase_log)
        self.entry = tk.Entry(root, width=30)
        self.entryGeneral = tk.Entry(root, width=30)
        self.intern_command_button = tk.Button(root, text="intern_command", command=self.intern_command)
        self.general_command_button = tk.Button(root, text="general_command", command=self.general_command)

        # Create the multi-checkbox widget and the print button
        self.multi_checkbox = MultiCheckboxButton(root, self.titles)
        self.print_button = ttk.Button(root, text="print_level", command=self.print_values)

        # Arrange the UI elements using grid layout
        mrow = 2                                     
        self.log_button.grid(column=0, row=mrow, padx=5, pady=5, sticky="ew")
        self.comm_connect_button.grid(column=1, row=mrow, padx=5, pady=5, sticky="ew")
        self.modem_query_epo_button.grid(column=2, row=mrow, padx=5, pady=5, sticky="ew")
        self.task_run_app_98_button.grid(column=3, row=mrow, padx=5, pady=5, sticky="ew")
        
        


        mrow = 3
        self.start_up_module_button.grid(column=0, row=mrow, padx=5, pady=5, sticky="ew")
        self.shut_down_module_button.grid(column=1, row=mrow, padx=5, pady=5, sticky="ew")
        self.toggle_button.grid(column=2, row=mrow, padx=10, pady=5, sticky="ew")
        self.erase_button.grid(column=3, row=mrow, padx=0, pady=5, sticky="ew")


        mrow = 4 
        self.set_rtc_reference_button.grid(column=0, row=mrow, padx=5, pady=5, sticky="ew")
        self.set_rtc_button.grid(column=1, row=mrow, padx=5, pady=5, sticky="ew")
        self.wait_for_completion_button.grid(column=2, row=mrow, padx=5, pady=5, sticky="ew")
        self.task_run_app_97_button.grid(column=3, row=mrow, padx=5, pady=5, sticky="ew")
        mrow = 5     
        self.query_configuration_button.grid(column=0, row=mrow, padx=5, pady=5, sticky="ew")
        self.set_configuration_button.grid(column=1, row=mrow, padx=5, pady=5, sticky="ew")
        self.print_firmware_versio_button.grid(column=2, row=mrow, padx=5, pady=5, sticky="ew")
        self.print_status_button.grid(column=3, row=mrow, padx=5, pady=5, sticky="ew")

        mrow = 6 
        self.epo_get_statue_button.grid(column=0, row=mrow, padx=5, pady=5, sticky="ew")
        self.epo_erase_button.grid(column=1, row=mrow, padx=5, pady=5, sticky="ew")
        self.load_ephemeris_in_buf_button.grid(column=2, row=mrow, padx=5, pady=5, sticky="ew")
        self.epo_load_from_buf_intern_button.grid(column=3, row=mrow, padx=5, pady=5, sticky="ew")
        
        mrow = 7
        self.disable_all_nmea_button.grid(column=0, row=mrow, padx=5, pady=5, sticky="ew")
        self.enable_nmea_button.grid(column=1, row=mrow, padx=5, pady=5, sticky="ew")
        self.subsys_full_cold_start_button.grid(column=2, row=mrow, padx=5, pady=5, sticky="ew")
        self.simu_speed_button.grid(column=3, row=mrow, padx=5, pady=5, sticky="ew")
        

        mrow = 8
        self.multi_checkbox.grid(column=0, row=mrow, padx=5, pady=5, sticky="ew")
        self.print_button.grid(column=1, row=mrow, padx=5, pady=5, sticky="ew")
        mrow = 9
        self.entry.grid(column=0, row=mrow, padx=10, pady=5, sticky="ew")
        self.intern_command_button.grid(column=1, row=mrow, padx=5, pady=5, sticky="ew")
        mrow = 10
        self.entryGeneral.grid(column=0, row=mrow, padx=10, pady=5, sticky="ew")
        self.general_command_button.grid(column=1, row=mrow, padx=5, pady=5, sticky="ew")
        

        # Boolean to control display toggling
        self.display_data = True
        self.sending = False

        # Start a separate thread to read data from UART
        self.running = True
        self.read_thread = threading.Thread(target=self.read_uart)
        self.read_thread.start()

    # Methods to send various GNSS commands via UART
    def print_status(self):
        log_command = "gnss PRINT_STATUS\r\n"
        self.serial_port.write(log_command.encode())

    def epo_get_statue(self):
        log_command = "gnss EPO_GET_STATUE\r\n"
        self.serial_port.write(log_command.encode())

    def epo_erase(self):
        log_command = "gnss EPO_ERASE\r\n"
        self.serial_port.write(log_command.encode())

    def epo_load_from_buf_intern(self):
        log_command = "gnss EPO_LOAD_FROM_BUF_INTERN\r\n"
        self.serial_port.write(log_command.encode())

    def start_up_module(self):
        #self.set_rtc()
        log_command = "gnss START_UP_MODULE\r\n"
        self.serial_port.write(log_command.encode())

    def shut_down_module(self):
        log_command = "gnss SHUT_DOWN_MODULE\r\n"
        self.serial_port.write(log_command.encode())

    def modem_query_epo(self):
        log_command = "gnss MODEM_QUERY_EPO\r\n"
        self.serial_port.write(log_command.encode())

    def comm_connect(self):
        log_command = "comm connect\r\n"
        self.serial_port.write(log_command.encode())

    def task_run_app_98(self):
        log_command = "task run app 98\r\n"
        self.serial_port.write(log_command.encode())

    def simu_speed(self):
        log_command = "gnssRotnSpeedChangeTest 1 100 100\r\n"
        self.serial_port.write(log_command.encode())
    

    def task_run_app_97(self):
        log_command = "task run app 97\r\n"
        self.serial_port.write(log_command.encode())

    def intern_command(self):
        command = "gnss INTERN_COMMAND " + self.entry.get() + '\r' + '\n'
        if command:
            self.serial_port.write(command.encode())
    def general_command(self):
        command = self.entryGeneral.get() + '\r' + '\n'
        if command:
            self.serial_port.write(command.encode())

    def set_rtc_reference(self):
        self.set_rtc()
        log_command = "gnss SET_RTC_REFERENCE\r\n"
        self.serial_port.write(log_command.encode())

    def set_configuration(self):
        log_command = "gnss SET_CONFIGURATION\r\n"
        self.serial_port.write(log_command.encode())

    def print_firmware_versio(self):
        log_command = "gnss PRINT_FIRMWARE_VERSION\r\n"
        self.serial_port.write(log_command.encode())

    def query_configuration(self):
        log_command = "gnss QUERY_CONFIGURATION\r\n"
        self.serial_port.write(log_command.encode())

    def disable_all_nmea(self):
        log_command = "gnss DISABLE_ALL_NMEA\r\n"
        self.serial_port.write(log_command.encode())

    def enable_nmea(self):
        log_command = "gnss ENABLE_NMEA\r\n"
        self.serial_port.write(log_command.encode())

    def subsys_full_cold_start(self):
        log_command = "gnss SUBSYS_FULL_COLD_START\r\n"
        self.serial_port.write(log_command.encode())

    def set_rtc(self):
        utc_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        self.serial_port.write(f"gnss SET_RTC \"{utc_time}\"\r\n".encode())
        log_command = "\r\n"
        self.serial_port.write(log_command.encode())

    def wait_for_completion(self):
        log_command = "gnss WAIT_FOR_COMPLETION 60000\r\n"
        self.serial_port.write(log_command.encode())

    def print_level(self):
        command = "gnss PRINT_LEVEL " + self.entryPrintLevel.get() + '\r' + '\n'
        if command:
            self.serial_port.write(command.encode())

    def load_ephemeris_in_buf(self):
        log_command = "\r\n"
        self.serial_port.write(log_command.encode())

    def erase_log(self):
        # Erase the contents of the text area
        self.text_area.delete('1.0', tk.END)

    def send_log_command(self):
        log_command = "log 511\r\n"
        self.serial_port.write(log_command.encode())

    # Function to print the selected log levels from checkboxes
    def print_values(self):
        values = self.multi_checkbox.get_values()
        log_levels = [1, 2, 4, 8, 16]  # Corresponding to ERROR, INFO, NMEA, IO, INTERRUPT
        result = 0
        for i, active in enumerate(values):
            if active:
                result |= log_levels[i]
        log_command = f"gnss PRINT_LEVEL {str(result)}\r\n"
        self.serial_port.write(log_command.encode())

    # Thread function to continuously read UART data
    def read_uart(self):
        while self.running:
            if self.serial_port.in_waiting > 0:
                data = self.serial_port.readline().decode(errors='ignore').strip()
                words = data.split()
                if self.display_data:
                    for word in words:
                        if word == "ERROR:" or word == "ERROR" or word == "error":
                            self.text_area.insert(tk.END, word + " ", "error")
                        elif word == "WARNING:" or word == "WARNING" or word == "warning":
                            self.text_area.insert(tk.END, word + " ", "warning")
                        elif word == "SUCCESS:" or word == "SUCCESS" or word == "success":
                            self.text_area.insert(tk.END, word + " ", "success")
                    self.text_area.insert(tk.END, data + '\n')
                    self.text_area.yview(tk.END)
                        
            time.sleep(0.01)  # Small sleep to prevent high CPU usage

    # Toggle display of UART data in the text area
    def toggle_display(self):
        self.display_data = not self.display_data
        self.toggle_button.config(text="Turn On Display" if not self.display_data else "Turn Off Display")

    # Function to load ephemeris data into buffer and send via UART
    def load_ephemeris_in_buf(self):
        if not self.sending:
            self.sending = True
            send_thread = threading.Thread(target=self.send_file_thread, args=("gnss LOAD_EPHEMERIS_IN_BUF ",))
            send_thread.start()

    # Thread function to send file data over UART
    def send_file_thread(self, PREAMBLE_STRING):
        folder_path = select_folder()

        if folder_path:
            # EPO_FILE_PATH_TEMPLATE = "C:/Users/pollux/Desktop/GetEPO/EPO_GPS_3_%d.DAT"
            # Construct the file path template with the selected folder
            EPO_FILE_PATH_TEMPLATE = os.path.join(folder_path, "EPO_GPS_3_%d.DAT")
            ENDWORD = "\r\n"  # Update end word to include \r and \n
            frame_number = 0  # Initialize frame number
            NUM_EPO_FILES = 5
            for f in range(1, NUM_EPO_FILES + 1):
                file_path = EPO_FILE_PATH_TEMPLATE % f
                if file_path:
                    with open(file_path, "rb") as file:
                        nbrJoursDownloades = 14
                        while frame_number < nbrJoursDownloades*128:  # 128 frames for one day then 14 days = 1792 frames
                            data = file.read(72)
                            if not data:
                                break

                            preamble = PREAMBLE_STRING
                            preamble += '{:04X}'.format(frame_number)
                            data_hex = ''.join(['{:02X}'.format(byte) for byte in data])  # Convert data to hex string
                            frame = preamble + data_hex + ENDWORD
                            print(f" Frame {frame_number}: {frame}")
                            # Open the file in append mode
                            # with open(r'C:/Users/GJ2640/Desktop/output.txt', 'a') as fileWrite:
                            #   fileWrite.write(f"Frame {frame_number}: {frame}")

                            self.serial_port.write(frame.encode())
                            time.sleep(0.05)  # Wait for 50 milliseconds before sending the next frame
                            frame_number = (frame_number + 1) % 65536  # Increment frame number and wrap around at 65536 (16-bit counter)
        self.sending = False
                    
    # Clean up resources and close the application
    def close(self):
        self.running = False
        self.read_thread.join()  # Ensure the reading thread has finished
        self.serial_port.close()  # Close the serial port
        self.root.destroy()  # Close the Tkinter window

if __name__ == "__main__":
    root = tk.Tk()
    app = UARTApp(root, "COM5", 115200)  # Adjust COM port and baud rate as necessary
    root.protocol("WM_DELETE_WINDOW", app.close)  # Ensure the app closes gracefully
    root.mainloop()
