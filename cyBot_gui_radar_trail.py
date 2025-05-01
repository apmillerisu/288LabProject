import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import socket
import threading
import time
import queue  # For thread-safe communication between socket thread and GUI thread
import math  # For map calculations

# --- Constants ---
# !!! IMPORTANT: Replace with your CyBot's actual IP address !!!
# Find this using 'ipconfig' in PuTTY connected via USB-Serial to the CyBot
CYBOT_IP = "192.168.1.1"  # <--- CHANGE THIS to your CyBot's IP
CYBOT_PORT = 288         # The port number CyBot listens on (usually 288)

# --- Global Variables ---
cybot_socket = None
is_connected = False
# Queue for messages from socket thread to GUI thread (thread-safe)
message_queue = queue.Queue()
# Flag to signal the listening thread to stop
stop_thread_flag = threading.Event()

# --- Network Communication ---


def connect_to_cybot():
    """Establishes a TCP socket connection to the CyBot."""
    global cybot_socket, is_connected
    if is_connected:
        status_label.config(text="Already connected.", foreground="orange")
        return

    try:
        status_label.config(text=f"Connecting to {CYBOT_IP}:{CYBOT_PORT}...",
                            foreground="black")
        app.update_idletasks()  # Update GUI immediately
        cybot_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Set a timeout for the connection attempt (e.g., 5 seconds)
        cybot_socket.settimeout(5.0)
        cybot_socket.connect((CYBOT_IP, CYBOT_PORT))
        # Disable timeout after connection is successful for blocking recv
        cybot_socket.settimeout(None)
        is_connected = True
        status_label.config(text="Connected to CyBot!", foreground="green")
        # Update button states
        connect_button.config(state=tk.DISABLED)
        disconnect_button.config(state=tk.NORMAL)
        send_button.config(state=tk.NORMAL)

        # Start the listening thread
        stop_thread_flag.clear()  # Ensure flag is reset
        listen_thread = threading.Thread(target=listen_for_messages, daemon=True)
        listen_thread.start()
        # Start processing messages from the queue
        app.after(100, process_incoming_messages)

    except socket.timeout:
        status_label.config(text="Connection timed out.", foreground="red")
        messagebox.showerror("Connection Error",
                         f"Connection to {CYBOT_IP}:{CYBOT_PORT} timed out.")
        is_connected = False
        cybot_socket = None
    except Exception as e:
        status_label.config(text=f"Connection failed: {e}", foreground="red")
        messagebox.showerror("Connection Error",
                         f"Could not connect to {CYBOT_IP}:{CYBOT_PORT}\nError: {e}\n\nMake sure the CyBot is running and the IP address is correct.")
        is_connected = False
        cybot_socket = None


def disconnect_from_cybot():
    """Signals the listening thread to stop and closes the socket connection."""
    global cybot_socket, is_connected
    if not is_connected:
        status_label.config(text="Not connected.", foreground="orange")
        return

    status_label.config(text="Disconnecting...", foreground="black")
    stop_thread_flag.set()  # Signal the listening thread to stop

    if cybot_socket:
        # Attempt to close the socket gracefully
        # Socket might already be closed if server disconnected
        try:
            # Shutdown may fail if socket is already closed, hence the broad except
            cybot_socket.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass  # Ignore errors during shutdown
        try:
            cybot_socket.close()
        except Exception:
            pass  # Ignore errors during close
        finally:
            cybot_socket = None  # Ensure socket is cleared

    is_connected = False
    status_label.config(text="Disconnected.", foreground="red")
    # Update button states
    connect_button.config(state=tk.NORMAL)
    disconnect_button.config(state=tk.DISABLED)
    send_button.config(state=tk.DISABLED)
    print("Disconnected.")


def send_command(event=None):  # Added event=None to handle <Return> key binding
    """Sends the command from the entry box to the CyBot."""
    if not is_connected or not cybot_socket:
        messagebox.showerror("Error", "Not connected to CyBot.")
        return
    command = command_entry.get()
    if not command:
        messagebox.showwarning("Warning", "Command cannot be empty.")
        return

    try:
        # Ensure command ends with newline for CyBot C code using readline/getByte loop
        if not command.endswith('\n'):
            command += '\n'
        cybot_socket.sendall(command.encode('utf-8'))
        # Display sent command in the raw data log
        raw_data_text.insert(tk.END, f"--> Sent: {command}")
        raw_data_text.see(tk.END)  # Scroll to the bottom
        command_entry.delete(0, tk.END)  # Clear entry box after sending
    except Exception as e:
        status_label.config(text=f"Send failed: {e}", foreground="red")
        messagebox.showerror("Send Error",
                         f"Failed to send command.\nError: {e}")
        disconnect_from_cybot()  # Assume connection is lost if send fails


def listen_for_messages():
    """
    Listens for incoming messages from the CyBot in a separate thread.
    Uses a loop that checks a flag for termination.
    Puts received messages into a thread-safe queue for the main GUI thread.
    """
    global cybot_socket, is_connected
    print("Listening thread started.")
    while not stop_thread_flag.is_set():
        try:
            # Use a timeout on recv to allow checking the stop flag periodically
            # This makes the thread more responsive to the disconnect signal
            cybot_socket.settimeout(0.2)  # Check stop flag every 0.2 seconds
            data_bytes = cybot_socket.recv(
                4096)  # Receive up to 4096 bytes
            cybot_socket.settimeout(
                None)  # Reset timeout after successful receive

            if data_bytes:
                # Decode safely, replacing errors, and put message in queue
                message = data_bytes.decode('utf-8', errors='replace')
                message_queue.put(message)
            else:
                # Empty data usually means the connection was closed by the server
                print("Connection closed by server (received empty data).")
                if not stop_thread_flag.is_set():  # Avoid duplicate disconnect logic
                    message_queue.put("CONNECTION_CLOSED")
                break  # Exit loop

        except socket.timeout:
            # This is expected when using timeout, just continue loop to check flag
            continue
        except Exception as e:
            # Handle other socket errors (e.g., connection reset)
            if not stop_thread_flag.is_set():  # Only report error if not initiated by us
                print(f"Socket error in listening thread: {e}")
                message_queue.put("CONNECTION_ERROR")
            break  # Exit loop on error

    print("Listening thread finished.")
    # Ensure disconnect state is reflected in GUI if thread exits unexpectedly
    if not stop_thread_flag.is_set():
        app.after(0, disconnect_from_cybot)  # Schedule disconnect in main thread


def process_incoming_messages():
    """Processes messages from the queue in the main GUI thread."""
    try:
        while not message_queue.empty():
            message = message_queue.get_nowait()  # Get message without blocking

            if message == "CONNECTION_CLOSED":
                if is_connected:  # Prevent multiple popups if already disconnected
                    messagebox.showinfo(
                        "Connection Info", "Connection closed by CyBot.")
                    disconnect_from_cybot()
                break  # Stop processing further messages from this connection
            elif message == "CONNECTION_ERROR":
                if is_connected:
                    messagebox.showerror("Connection Error",
                                     "Socket error occurred.")
                    disconnect_from_cybot()
                break  # Stop processing further messages from this connection
            else:
                # --- Update Raw Data Display ---
                # Add timestamp for clarity
                timestamp = time.strftime("%H:%M:%S", time.localtime())
                raw_data_text.insert(tk.END, f"[{timestamp}] {message}")
                # Ensure newline if message doesn't end with one visually
                if not message.endswith('\n'):
                    raw_data_text.insert(tk.END, "\n")
                raw_data_text.see(tk.END)  # Scroll to bottom

                # --- Parse message and update Map & Sensor Status ---
                parse_cybot_message(message)

    except queue.Empty:
        pass  # No messages to process right now

    # Schedule this function to run again if still connected or thread running
    if is_connected or not stop_thread_flag.is_set():
        app.after(100, process_incoming_messages)  # Check queue every 100ms


def parse_cybot_message(message):
    """Parses a message string from CyBot and calls update functions."""
    lines = message.strip().split('\n')  # Handle multi-line messages
    for line in lines:
        line = line.strip()
        if not line:
            continue  # Skip empty lines

        print(f"Parsing: {line}")  # Debug print

        # --- Add Parsing Rules based on your CyBot's C code output format ---
        try:
            if line.startswith("STATUS:"):
                # Example: "STATUS:BUMP_L=1,BUMP_R=0,CLIFF_L=0,CLIFF_FL=0,CLIFF_FR=0,CLIFF_R=0,PING=100.5"
                parts = line[len("STATUS:"):].split(',')
                status_data = {}
                for part in parts:
                    key, value = part.split('=')
                    status_data[key] = value  # Keep as string initially
                update_sensor_status(status_data)
            elif line.startswith("SCAN:"):
                # Example: "SCAN:ANGLE=90.00,DIST_MM=250.00,IR_RAW=1200"
                parts = line[len("SCAN:"):].split(',')
                scan_data = {}
                for part in parts:
                    key, value = part.split('=')
                    scan_data[key] = float(value)
                update_map_with_scan(scan_data)
            elif line.startswith("INFO:"):
                # Example: "INFO:Moving forward" or "INFO:Bump sensor triggered!"
                info_message = line[len("INFO:"):]
                # Log the message in the text area
                raw_data_text.insert(tk.END, f"INFO: {info_message}\n")
                raw_data_text.see(tk.END)
            # Add more specific parsing rules as needed

        except Exception as e:
            print(f"Error parsing line '{line}': {e}")


# --- GUI Update Functions (Implement these based on parsing) ---


def update_sensor_status(status_data):
    """Updates the sensor visualization canvas based on parsed status."""
    # Example: status_data might be {"BUMP_L": "1", "BUMP_R": "0", "CLIFF_L": "0", ...}
    print(f"Updating sensor status with: {status_data}")

    # Clear previous dynamic drawings (use a specific tag)
    sensor_canvas.delete("status_indicator")

    # --- Default appearance ---
    # Bumpers (lines or small rectangles)
    left_bumper_color = "grey"
    right_bumper_color = "grey"
    # Cliff sensors (small circles/dots)
    cliff_l_color = "grey"
    cliff_fl_color = "grey"
    cliff_fr_color = "grey"
    cliff_r_color = "grey"
    # Ping
    ping_color = "grey"

    # --- Parse the status string and update colors ---
    # This parsing is basic, make it robust for your format
    if "BUMP_L" in status_data and status_data["BUMP_L"] == '1':
        left_bumper_color = "red"
    if "BUMP_R" in status_data and status_data["BUMP_R"] == '1':
        right_bumper_color = "red"
    if "CLIFF_L" in status_data and status_data["CLIFF_L"] == '1':
        cliff_l_color = "orange"
    if "CLIFF_FL" in status_data and status_data["CLIFF_FL"] == '1':
        cliff_fl_color = "orange"
    if "CLIFF_FR" in status_data and status_data["CLIFF_FR"] == '1':
        cliff_fr_color = "orange"
    if "CLIFF_R" in status_data and status_data["CLIFF_R"] == '1':
        cliff_r_color = "orange"
    if "PING"in status_data and float(status_data["PING"]) > 0:
        ping_color = "blue"

    # --- Redraw indicators with updated colors ---
    # Coordinates are approximate relative to the base Roomba circle (50,50,150,150)
    # Left Bumper
    sensor_canvas.create_line(50, 80, 70, 60,
                            fill=left_bumper_color, width=4,
                            tags="status_indicator")
    # Right Bumper
    sensor_canvas.create_line(150, 80, 130, 60,
                            fill=right_bumper_color, width=4,
                            tags="status_indicator")
    # Cliff Left
    sensor_canvas.create_oval(65, 55, 75, 65,
                            fill=cliff_l_color, outline="black",
                            tags="status_indicator")
    # Cliff Front Left
    sensor_canvas.create_oval(85, 45, 95, 55,
                            fill=cliff_fl_color, outline="black",
                            tags="status_indicator")
    # Cliff Front Right
    sensor_canvas.create_oval(105, 45, 115, 55,
                            fill=cliff_fr_color, outline="black",
                            tags="status_indicator")
    # Cliff Right
    sensor_canvas.create_oval(125, 55, 135, 65,
                            fill=cliff_r_color, outline="black",
                            tags="status_indicator")
    # Ping
    sensor_canvas.create_oval(95, 10, 105, 20,
                            fill=ping_color, outline="black",
                            tags="status_indicator")


def update_map_with_scan(scan_data):
    """Updates the map display based on parsed scan data."""
    # Example: scan_data might be {"ANGLE": 90.0, "DIST_MM": 500.0, "IR_RAW": 1200}
    print(f"Updating map with scan: {scan_data}")

    try:
        # --- Extract data from the dictionary ---
        angle_deg = scan_data.get("ANGLE")
        dist_mm = scan_data.get("DIST_MM")

        if angle_deg is not None and dist_mm is not None:
            # --- Convert polar (angle, dist) to Cartesian (x, y) relative to robot ---
            # Assume 0 degrees is forward, positive angle is to the robot's LEFT
            # Convert angle to radians for math functions, adjust so 0 is forward (along +y axis in math)
            angle_rad = math.radians(90 - angle_deg)

            # Convert distance to meters for consistency if desired, or use pixels/mm
            dist_pixels = dist_mm / 10  # Example scale: 1 pixel = 10 mm = 1 cm

            # --- Get current map dimensions and center ---
            # Note: This assumes the robot is always at the center of the map display.
            # A more advanced map would track the robot's position.
            map_center_x = map_canvas.winfo_width() / 2
            map_center_y = map_canvas.winfo_height() / 2

            # Calculate point relative to map center (y is inverted in tkinter canvas)
            point_x = map_center_x + dist_pixels * math.cos(angle_rad)
            point_y = map_center_y - dist_pixels * math.sin(
                angle_rad)  # Subtract because y increases downwards

            # --- Draw the detected point ---
            # Use a specific tag to potentially clear old scan points later
            radius = 2  # Size of the point
            map_canvas.create_oval(point_x - radius, point_y - radius,
                                   point_x + radius, point_y + radius,
                                   fill="blue", outline="blue",
                                   tags="scan_point")
        else:
            print(
                f"Could not parse angle or distance from scan data: {scan_data}")

    except Exception as e:
        print(f"Error processing scan data '{scan_data}': {e}")


def update_map_with_bump(bump_info_string):
    """Updates the map display based on a bump event."""
    # Example: bump_info_string might be "LEFT" or "RIGHT" or "FRONT"
    print(f"Updating map with bump: {bump_info_string}")

    # --- Get current map dimensions and center ---
    map_center_x = map_canvas.winfo_width() / 2
    map_center_y = map_canvas.winfo_height() / 2

    # --- Determine bump location relative to robot center ---
    bump_x, bump_y = map_center_x, map_center_y
    radius = 5  # Size of the bump indicator
    robot_radius_pixels = 15  # Approximate robot radius for drawing bump location

    if "LEFT" in bump_info_string:
        bump_x -= robot_radius_pixels
    elif "RIGHT" in bump_info_string:
        bump_x += robot_radius_pixels
    elif "FRONT" in bump_info_string:  # You might need separate BUMP_L/R for front
        bump_y -= robot_radius_pixels  # Y is inverted
    # Add more specific locations if needed

    # --- Draw a bump indicator (e.g., a red X or square) ---
    map_canvas.create_rectangle(bump_x - radius, bump_y - radius,
                                 bump_x + radius, bump_y + radius,
                                 fill="red", outline="red",
                                 tags="bump_event")



def clear_map_features(tag_to_clear):
    """Utility function to clear specific items from the map canvas."""
    map_canvas.delete(tag_to_clear)


# --- GUI Setup ---
app = tk.Tk()
app.title("CyBot Control Center - Ice Cream Truck")
app.geometry("900x700")  # Increased size

# --- Style ---
style = ttk.Style()
style.theme_use('clam')  # Or 'alt', 'default', 'classic'

# --- Connection Frame ---
connection_frame = ttk.LabelFrame(app, text="Connection")
connection_frame.pack(pady=5, padx=10, fill="x")

status_label = ttk.Label(connection_frame, text="Disconnected",
                        foreground="red", font=("Arial", 10, "bold"))
status_label.pack(side=tk.LEFT, padx=5, pady=5)

connect_button = ttk.Button(connection_frame, text="Connect",
                            command=connect_to_cybot, style='TButton')
connect_button.pack(side=tk.LEFT, padx=5, pady=5)

disconnect_button = ttk.Button(connection_frame, text="Disconnect",
                                 command=disconnect_from_cybot,
                                 state=tk.DISABLED, style='W.TButton')
disconnect_button.pack(side=tk.LEFT, padx=5, pady=5)

# --- Command Frame ---
command_frame = ttk.LabelFrame(app, text="Manual Command")
command_frame.pack(pady=5, padx=10, fill="x")

command_entry = ttk.Entry(command_frame, width=60)
command_entry.pack(side=tk.LEFT, padx=5, pady=5, expand=True, fill="x")
# Send command when Enter key is pressed in the entry field
command_entry.bind("<Return>", send_command)

send_button = ttk.Button(command_frame, text="Send",
                          command=send_command, state=tk.DISABLED,
                          style='TButton')
send_button.pack(side=tk.LEFT, padx=5, pady=5)

# --- Main Paned Window (Resizable Areas) ---
# Use PanedWindow for resizable sections
paned_window = ttk.PanedWindow(app, orient=tk.HORIZONTAL)
paned_window.pack(pady=10, padx=10, expand=True, fill="both")

# --- Left Pane (Raw Data & Sensor Status) ---
left_pane_frame = ttk.Frame(paned_window, width=350)  # Initial width
paned_window.add(left_pane_frame, weight=1)  # Allow resizing, less weight than map

# Raw Data Area
raw_data_frame = ttk.LabelFrame(left_pane_frame, text="Raw Data Log")
# Make raw data expand vertically
raw_data_frame.pack(pady=5, padx=5, expand=True, fill="both")
# Use ScrolledText for automatic scrollbars
raw_data_text = scrolledtext.ScrolledText(
    raw_data_frame, wrap=tk.WORD, height=15, width=40, font=("Consolas", 9))
raw_data_text.pack(expand=True, fill="both")

# Sensor Status Area
sensor_frame = ttk.LabelFrame(left_pane_frame, text="Sensor Status")
sensor_frame.pack(pady=5, padx=5, fill="x",
                    side=tk.BOTTOM)  # Place at bottom of left pane
# Canvas for drawing sensor visualization
sensor_canvas = tk.Canvas(sensor_frame, width=200, height=200, bg="white",
                           highlightthickness=1, highlightbackground="grey")
sensor_canvas.pack(pady=5)
# Initial drawing of the Roomba base and default status
sensor_canvas.create_oval(50, 50, 150, 150, outline="black",
                         width=2, tags="base")  # Main body
sensor_canvas.create_rectangle(
    90, 35, 110, 50, outline="black", width=2, tags="base")  # Top bump/lid part
update_sensor_status(
    {"BUMP_L": "0", "BUMP_R": "0", "CLIFF_L": "0", "CLIFF_FL": "0",
     "CLIFF_FR": "0", "CLIFF_R": "0", "PING": "0"})  # Draw initial grey state



# --- Right Pane (Map) ---
map_frame = ttk.LabelFrame(paned_window, text="Test Field Map (Top-Down View)")
paned_window.add(map_frame, weight=3)  # Allow resizing, give map more weight

map_canvas = tk.Canvas(map_frame, bg="lightgrey",
                         highlightthickness=1, highlightbackground="grey")
map_canvas.pack(expand=True, fill="both")

# Draw robot starting position (center) - slightly larger
robot_size = 10
# Draw robot after canvas is sized


def draw_robot_on_map(event=None):
    map_canvas.delete("robot")  # Clear previous robot drawing
    cx = map_canvas.winfo_width() / 2
    cy = map_canvas.winfo_height() / 2
    # Draw a circle for the robot body
    map_canvas.create_oval(cx - robot_size, cy - robot_size,
                           cx + robot_size, cy + robot_size,
                           fill="darkgreen", outline="black", width=2,
                           tags="robot")
    # Draw a line indicating forward direction (upwards)
    map_canvas.create_line(cx, cy, cx, cy - robot_size, fill="white", width=3,
                            arrow=tk.LAST, tags="robot")


map_canvas.bind("<Configure>",
                  draw_robot_on_map)  # Redraw robot if map resizes

# Add buttons to clear map features
map_button_frame = ttk.Frame(map_frame)
map_button_frame.pack(side=tk.BOTTOM, fill="x", pady=2)
clear_scan_button = ttk.Button(
    map_button_frame, text="Clear Scan Points",
    command=lambda: clear_map_features("scan_point"))
clear_scan_button.pack(side=tk.LEFT, padx=5)
clear_bump_button = ttk.Button(
    map_button_frame, text="Clear Bump Events",
    command=lambda: clear_map_features("bump_event"))
clear_bump_button.pack(side=tk.LEFT, padx=5)


# --- Main Loop ---
# Set protocol for window close ('WM_DELETE_WINDOW')
# This ensures disconnection happens if user clicks the 'X' button
def on_closing():
    if messagebox.askokcancel("Quit", "Do you want to quit?"):
        disconnect_from_cybot()
        # Allow time for disconnect to process before destroying window
        app.after(200, app.destroy)


app.protocol("WM_DELETE_WINDOW", on_closing)

# Start the Tkinter event loop
app.mainloop()

# --- Cleanup (Optional - usually handled by on_closing) ---
print("Application closing.")
# Ensure thread flag is set if somehow bypassed on_closing
stop_thread_flag.set()
