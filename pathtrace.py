# LabProjectAlmostWorking/GUI.py
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import socket
import threading
import time
import queue # For thread-safe communication between socket thread and GUI thread
import math  # For map calculations
import statistics # For median/average if needed

# --- Constants ---
# !!! IMPORTANT: Replace with your CyBot's actual IP address !!!
CYBOT_IP = "192.168.1.1"  # <--- CHANGE THIS to your CyBot's IP
CYBOT_PORT = 288
# Define commands
CMD_FORWARD = "w\n"
CMD_BACKWARD = "s\n"
CMD_LEFT = "a\n"
CMD_LEFT_SHORT = "z\n"
CMD_RIGHT = "d\n"
CMD_RIGHT_SHORT = "c\n"
CMD_SCAN = "m\n"
CMD_JINGLE = "j\n"
CMD_IGNORE = "l\n"

# Map and Trail Constants
MAP_SCALE = 2.0 # pixels / cm (e.g., 1 meter = 100 cm = 200 pixels)
ROBOT_RADIUS_PIXELS = 15 # Approximate visual size on map
ROBOT_REAL_RADIUS_CM = 15
SENSOR_FORWARD_OFFSET_CM = 5 # Distance sensor is forward from robot center (e.g., 30cm). Adjust as needed.

# Object Detection Constants (Tune these)
OBJECT_MAX_DIST_CM = 250.0 # Ignore points further than this for object detection
OBJECT_MIN_ANGLE_WIDTH_DEG = 6.0 # Minimum angular size to be considered an object
OBJECT_MIN_POINTS = 3 # Minimum consecutive points to form an object
OBJECT_EDGE_THRESHOLD_CM = 15.0 # Min distance change (cm) to detect edge (Currently PING-related, not used in IR logic below)

# ---vvv--- MODIFIED/NEW IR DETECTION CONSTANTS ---vvv---
IR_MIN_STRENGTH_FOR_CONSIDERATION = 750 # Minimum average IR value to consider a point part of an object. Tune this!
                                        # If objects have IR ~500, lower this to ~450-500.
IR_EDGE_THRESHOLD_RISE = 300    # Minimum IR value increase (current_ir - prev_ir) to detect a rising edge.
IR_EDGE_THRESHOLD_DROP = 250      # Minimum IR value decrease (prev_ir - current_ir) to detect a falling edge.
DEBUG_OBJECT_DETECTION = True     # Set to True to get print statements for debugging object detection logic.
# ---^^^--- MODIFIED/NEW IR DETECTION CONSTANTS ---^^^---


# --- Add these near other constants ---
IR_MIN_RAW = 400  # Raw value considered "far" for plotting on radar
IR_MAX_RAW = 1500.0 # Raw value considered "close" for plotting on radar
IR_VALID_MIN = 50   # Minimum raw value to consider plotting on radar (avoids plotting noise)
# IR_MIN_STRENGTH_FOR_CONSIDERATION was moved up

# Cliff Color Thresholds
WHITE_THRESHOLD = 2600
BLACK_THRESHOLD = 500

# --- Global Variables ---
cybot_socket = None
is_connected = False
message_queue = queue.Queue()
stop_thread_flag = threading.Event()

# Robot Pose (Position and Orientation) - Initialized when map is ready
robot_x = 0.0
robot_y = 0.0
robot_angle_deg = 90.0 # 90 degrees = facing up (North) in world frame

# Scan Data Storage
current_scan_buffer = [] # Temp buffer while scan is in progress
last_scan_data = [] # Stores the points (angle_deg, dist_cm, ir_raw) of the last completed scan

# --- Network Communication ---
# (connect_to_cybot, disconnect_from_cybot, send_command functions remain the same)
def connect_to_cybot():
    """Establishes a socket connection to the CyBot."""
    global cybot_socket, is_connected, robot_x, robot_y, robot_angle_deg
    if is_connected:
        status_label.config(text="Already connected.", foreground="orange")
        return

    # Reset robot angle on new connection
    robot_angle_deg = 90.0

    try:
        status_label.config(text=f"Connecting to {CYBOT_IP}:{CYBOT_PORT}...", foreground="black")
        app.update_idletasks() # Force GUI update

        cybot_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        cybot_socket.settimeout(5.0) # Set connection timeout
        cybot_socket.connect((CYBOT_IP, CYBOT_PORT))
        cybot_socket.settimeout(None) # Reset timeout for blocking operations
        is_connected = True
        status_label.config(text="Connected to CyBot!", foreground="green")

        # Update button states
        connect_button.config(state=tk.DISABLED)
        disconnect_button.config(state=tk.NORMAL)
        scan_button.config(state=tk.NORMAL)
        jingle_button.config(state=tk.NORMAL)

        # Bind keys and initialize robot position on map
        bind_keys()
        app.after(100, initialize_robot_position) # Initialize after a short delay

        # Start the listening thread
        stop_thread_flag.clear()
        listen_thread = threading.Thread(target=listen_for_messages, daemon=True)
        listen_thread.start()

        # Start processing incoming messages
        app.after(100, process_incoming_messages)

    except socket.timeout:
        status_label.config(text="Connection timed out.", foreground="red")
        messagebox.showerror("Connection Error", f"Connection to {CYBOT_IP}:{CYBOT_PORT} timed out.")
        is_connected = False
        cybot_socket = None
    except Exception as e:
        status_label.config(text=f"Connection failed: {e}", foreground="red")
        messagebox.showerror("Connection Error", f"Could not connect to {CYBOT_IP}:{CYBOT_PORT}\nError: {e}")
        is_connected = False
        cybot_socket = None

def disconnect_from_cybot():
    """Closes the socket connection and updates GUI state."""
    global cybot_socket, is_connected
    if not is_connected:
        return

    status_label.config(text="Disconnecting...", foreground="black")
    stop_thread_flag.set() # Signal the listening thread to stop

    if cybot_socket:
        try:
            # Shutdown socket to signal the other end
            cybot_socket.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass # Ignore errors if socket already closed
        try:
            cybot_socket.close()
        except Exception:
            pass # Ignore errors if socket already closed
        finally:
            cybot_socket = None

    is_connected = False
    status_label.config(text="Disconnected.", foreground="red")

    # Update button states
    connect_button.config(state=tk.NORMAL)
    disconnect_button.config(state=tk.DISABLED)
    scan_button.config(state=tk.DISABLED)
    jingle_button.config(state=tk.DISABLED)

    # Unbind keys
    unbind_keys()
    print("Disconnected.")

def send_command(command_to_send):
    """Sends a command string to the connected CyBot."""
    if not is_connected or not cybot_socket:
        print("Warning: Cannot send command, not connected.")
        return
    if not command_to_send:
        print("Warning: Command cannot be empty.")
        return

    try:
        # Ensure command ends with a newline
        if not command_to_send.endswith('\n'):
            command_to_send += '\n'
        # Encode and send
        cybot_socket.sendall(command_to_send.encode('utf-8'))
        # Log sent command
        raw_data_text.insert(tk.END, f"--> Sent: {command_to_send}")
        raw_data_text.see(tk.END) # Scroll to the end
    except Exception as e:
        status_label.config(text=f"Send failed: {e}", foreground="red")
        messagebox.showerror("Send Error", f"Failed to send command.\nError: {e}")
        # Disconnect on send error
        app.after(0, disconnect_from_cybot)


# --- Key Binding Functions ---
# (handle_keypress, bind_keys, unbind_keys functions remain the same)
def handle_keypress(event):
    """Handles key presses for robot control if the log isn't focused."""
    if app.focus_get() != raw_data_text: # Prevent key capture when log is focused
        key = event.keysym.lower()
        # print(f"Key pressed: {key}") # Reduce noise
        if key == 'w': send_command(CMD_FORWARD)
        elif key == 's': send_command(CMD_BACKWARD)
        elif key == 'a': send_command(CMD_LEFT)
        elif key == 'z': send_command(CMD_LEFT_SHORT)
        elif key == 'd': send_command(CMD_RIGHT)
        elif key == 'c': send_command(CMD_RIGHT_SHORT)
        elif key == 'm': send_command(CMD_SCAN)
        elif key == 'j': send_command(CMD_JINGLE)
        elif key == 'l': send_command(CMD_IGNORE)

def bind_keys():
    """Binds WASD, M, J keys to the handler."""
    print("Binding keys...")
    app.bind_all('<KeyPress-w>', handle_keypress)
    app.bind_all('<KeyPress-s>', handle_keypress)
    app.bind_all('<KeyPress-a>', handle_keypress)
    app.bind_all('<KeyPress-z>', handle_keypress)
    app.bind_all('<KeyPress-d>', handle_keypress)
    app.bind_all('<KeyPress-c>', handle_keypress)
    app.bind_all('<KeyPress-m>', handle_keypress)
    app.bind_all('<KeyPress-j>', handle_keypress)
    app.bind_all('<KeyPress-l>', handle_keypress)

def unbind_keys():
    """Unbinds control keys."""
    print("Unbinding keys...")
    app.unbind_all('<KeyPress-w>')
    app.unbind_all('<KeyPress-s>')
    app.unbind_all('<KeyPress-a>')
    app.unbind_all('<KeyPress-z>')
    app.unbind_all('<KeyPress-d>')
    app.unbind_all('<KeyPress-c>')
    app.unbind_all('<KeyPress-m>')
    app.unbind_all('<KeyPress-j>')
    app.unbind_all('<KeyPress-l>')


# --- Listener Thread and Message Processing ---
# (listen_for_messages remains the same)
def listen_for_messages():
    """Listens for incoming messages from the CyBot socket in a separate thread."""
    global cybot_socket, is_connected
    print("Listening thread started.")
    buffer = ""
    while not stop_thread_flag.is_set():
        try:
            # Use a small timeout to prevent blocking indefinitely
            # Allows checking stop_thread_flag periodically
            cybot_socket.settimeout(0.2)
            data_bytes = cybot_socket.recv(1024) # Read in chunks
            cybot_socket.settimeout(None) # Reset timeout after successful read

            if data_bytes:
                message_part = data_bytes.decode('utf-8', errors='replace')
                buffer += message_part
                # Process complete lines (ending with \n) from the buffer
                while '\n' in buffer:
                    message, buffer = buffer.split('\n', 1)
                    message_queue.put(message + '\n') # Add message to the thread-safe queue
            else:
                # Socket closed by the server
                print("Connection closed by server (received empty data).")
                if not stop_thread_flag.is_set():
                    message_queue.put("CONNECTION_CLOSED\n") # Signal main thread
                break # Exit thread loop

        except socket.timeout:
            # No data received, loop continues to check stop_thread_flag
            continue
        except socket.error as e:
            # Handle socket errors (e.g., connection reset)
            if not stop_thread_flag.is_set():
                print(f"Socket error in listening thread: {e}")
                message_queue.put("CONNECTION_ERROR\n") # Signal main thread
            break # Exit thread loop
        except Exception as e:
            # Handle other potential errors during recv or decode
            if not stop_thread_flag.is_set():
                 print(f"Unexpected error in listening thread: {e}")
                 message_queue.put("CONNECTION_ERROR\n") # Signal main thread
            break # Exit thread loop

    print("Listening thread finished.")
    # If the thread finishes unexpectedly while still "connected", trigger disconnect
    if not stop_thread_flag.is_set() and is_connected:
        app.after(0, disconnect_from_cybot) # Schedule disconnect in main GUI thread


# (process_incoming_messages remains the same - filtering STATUS from log)
def process_incoming_messages():
    """Processes messages from the queue in the main GUI thread."""
    global is_connected, stop_thread_flag
    try:
        while not message_queue.empty():
            message = message_queue.get_nowait() # Get message without blocking

            # Check for special signals from the listener thread
            if message == "CONNECTION_CLOSED\n":
                 if is_connected:
                     messagebox.showinfo("Connection Info", "Connection closed by CyBot.")
                     disconnect_from_cybot()
                 break # Stop processing queue on disconnect
            elif message == "CONNECTION_ERROR\n":
                 if is_connected:
                     messagebox.showerror("Connection Error", "Socket error occurred.")
                     disconnect_from_cybot()
                 break # Stop processing queue on error
            else:
                # Process regular messages
                timestamp = time.strftime("%H:%M:%S", time.localtime())
                message_content = message.strip() # Get content for checking prefix

                # Determine if we should log this message based on its prefix
                log_this_message = not message_content.startswith("STATUS:")

                # Log the message ONLY if the flag is True (i.e., not a STATUS message)
                if log_this_message:
                    raw_data_text.insert(tk.END, f"[{timestamp}] {message}") # Log original message
                    raw_data_text.see(tk.END) # Scroll log

                # ALWAYS parse the message, regardless of whether it was logged or not
                # This ensures sensor display updates and other actions still occur
                parse_cybot_message(message) # Parse the original message

    except queue.Empty:
        pass # No messages currently in queue, perfectly normal
    except Exception as e:
        # Catch any unexpected error during processing. Keeping this is useful.
        print(f"ERROR processing message in GUI: {e}")


    # Schedule the next check if the connection is active or thread hasn't been stopped
    if is_connected or not stop_thread_flag.is_set():
         app.after(100, process_incoming_messages) # Check again in 100ms


# (parse_cybot_message remains the same - handling END SCAN etc.)
def parse_cybot_message(message):
    """Parses a single message line from CyBot and calls appropriate update functions."""
    global current_scan_buffer, last_scan_data
    line = message.strip() # Remove leading/trailing whitespace and newline
    if not line: return # Skip empty lines

    try:
        # Check for the more specific "END SCAN" marker first
        # Ensure your C code sends something like "SCAN: END SCAN\n"
        if "END SCAN" in line.upper() and line.startswith("SCAN:"):
            if DEBUG_OBJECT_DETECTION: print(f"\nScan END marker received: '{line}'")
            if DEBUG_OBJECT_DETECTION: print(f"Buffer size BEFORE processing END: {len(current_scan_buffer)}")
            if current_scan_buffer:
                last_scan_data = current_scan_buffer[:]
                current_scan_buffer = []
                if DEBUG_OBJECT_DETECTION: print(f"Copied data to last_scan_data (size: {len(last_scan_data)}). Cleared buffer.")
                # Use app.after to ensure GUI updates happen safely in the main thread
                app.after(10, draw_radar_plot) # Schedule radar plot
                app.after(20, detect_and_plot_objects) # Schedule object detection
            else:
                if DEBUG_OBJECT_DETECTION: print("Scan END received, but current_scan_buffer is empty. No plotting.")
            return # Stop processing this line further

        # Process other message types
        elif line.startswith("STATUS:"):
            update_sensor_status(line[len("STATUS:"):])
        elif line.startswith("SCAN:"): # Handles regular scan data points
             append_scan_data(line[len("SCAN:"):], is_mock_data=False)
        elif line.startswith("MOVE:"): # Handle movement updates
             update_robot_position_and_trail(line[len("MOVE:"):])
        elif line.startswith("BUMP_EVENT:"): # Handle bump events
             update_map_with_bump(line[len("BUMP_EVENT:"):])
        elif line.startswith("INFO:") or line.startswith("DEBUG:") or line.startswith("ERROR:") or line.startswith("ACK:"):
             pass # Just log these types of messages (logging happens in process_incoming_messages)

    except Exception as e:
        print(f"Error parsing line '{line}': {e}")


# --- GUI Update Functions ---
# (initialize_robot_position, update_sensor_status, append_scan_data,
#  update_map_with_scan, update_map_with_bump
#  functions remain mostly the same, except for logging added to update_robot_position_and_trail)
def initialize_robot_position():
    """Sets the robot's initial position to the center of the map canvas."""
    global robot_x, robot_y
    map_canvas.update_idletasks() # Ensure canvas size is calculated before getting dimensions
    map_width = map_canvas.winfo_width()
    map_height = map_canvas.winfo_height()
    if map_width > 1 and map_height > 1: # Make sure canvas has valid dimensions
        robot_x = map_width / 2
        robot_y = map_height / 2
        print(f"Robot initialized at map center: ({robot_x:.1f}, {robot_y:.1f})")
        draw_robot_on_map() # Draw robot at the initial position
    else:
        print("Map canvas not ready for initialization, retrying...")
        app.after(100, initialize_robot_position) # Retry after a short delay

def update_sensor_status(status_string):
    """Parses the STATUS string and updates the sensor display elements."""
    sensor_canvas.delete("status_indicator")
    left_bumper_color, right_bumper_color = "grey", "grey"
    cliff_l_sig_val_str, cliff_fl_sig_val_str, cliff_fr_sig_val_str, cliff_r_sig_val_str = "N/A", "N/A", "N/A", "N/A"
    cliff_l_color, cliff_fl_color, cliff_fr_color, cliff_r_color = "grey", "grey", "grey", "grey"
    ping_val = "N/A"
    heading_val = "N/A" # <<< MODIFIED: Initialize heading_val

    try:
        parts = status_string.split(',')
        for part in parts:
            key_value = part.split('=')
            if len(key_value) == 2:
                key, value_str = key_value[0].strip(), key_value[1].strip()
                if key == "BUMP_L" and value_str == '1': left_bumper_color = "red"
                elif key == "BUMP_R" and value_str == '1': right_bumper_color = "red"
                elif key == "CLIFF_L_SIG":
                    cliff_l_sig_val_str = value_str
                    try:
                        signal = int(value_str)
                        if signal >= WHITE_THRESHOLD: cliff_l_color = "blue"
                        elif signal <= BLACK_THRESHOLD: cliff_l_color = "red"
                        else: cliff_l_color = "grey"
                    except ValueError: cliff_l_color = "grey"
                elif key == "CLIFF_FL_SIG":
                    cliff_fl_sig_val_str = value_str
                    try:
                        signal = int(value_str)
                        if signal >= WHITE_THRESHOLD: cliff_fl_color = "blue"
                        elif signal <= BLACK_THRESHOLD: cliff_fl_color = "red"
                        else: cliff_fl_color = "grey"
                    except ValueError: cliff_fl_color = "grey"
                elif key == "CLIFF_FR_SIG":
                    cliff_fr_sig_val_str = value_str
                    try:
                        signal = int(value_str)
                        if signal >= WHITE_THRESHOLD: cliff_fr_color = "blue"
                        elif signal <= BLACK_THRESHOLD: cliff_fr_color = "red"
                        else: cliff_fr_color = "grey"
                    except ValueError: cliff_fr_color = "grey"
                elif key == "CLIFF_R_SIG":
                    cliff_r_sig_val_str = value_str
                    try:
                        signal = int(value_str)
                        if signal >= WHITE_THRESHOLD: cliff_r_color = "blue"
                        elif signal <= BLACK_THRESHOLD: cliff_r_color = "red"
                        else: cliff_r_color = "grey"
                    except ValueError: cliff_r_color = "grey"
                elif key == "PING":
                    try: ping_val = f"{float(value_str):.1f}"
                    except ValueError: ping_val = "Invalid"
                elif key == "Heading": # This part was already in your code
                    try:
                        # Format as integer degrees directly
                        heading_val = f"{int(value_str)}°"
                    except ValueError:
                        heading_val = "Invalid"

    except Exception as e:
        print(f"Error parsing status string '{status_string}': {e}")
        cliff_l_sig_val_str, cliff_fl_sig_val_str, cliff_fr_sig_val_str, cliff_r_sig_val_str = "Err", "Err", "Err", "Err"
        ping_val = "Err"
        heading_val = "Err" # Ensure heading_val is also set in case of an earlier error
        cliff_l_color, cliff_fl_color, cliff_fr_color, cliff_r_color = "grey", "grey", "grey", "grey"

    # Update GUI Elements
    sensor_canvas.create_line(50, 80, 70, 60, fill=left_bumper_color, width=4, tags="status_indicator")
    sensor_canvas.create_line(150, 80, 130, 60, fill=right_bumper_color, width=4, tags="status_indicator")
    try:
        sensor_canvas.itemconfig("cliff_l_indicator", fill=cliff_l_color)
        sensor_canvas.itemconfig("cliff_fl_indicator", fill=cliff_fl_color)
        sensor_canvas.itemconfig("cliff_fr_indicator", fill=cliff_fr_color)
        sensor_canvas.itemconfig("cliff_r_indicator", fill=cliff_r_color)
    except tk.TclError as e:
        print(f"Error updating cliff indicator colors: {e}")
    cliff_l_sig_label.config(text=f"L: {cliff_l_sig_val_str}")
    cliff_fl_sig_label.config(text=f"FL: {cliff_fl_sig_val_str}")
    cliff_fr_sig_label.config(text=f"FR: {cliff_fr_sig_val_str}")
    cliff_r_sig_label.config(text=f"R: {cliff_r_sig_val_str}")
    
    # Your existing ping_label will now correctly include the heading
    # The format "degrees" was already in your code for the label, so I'll use "°" from parsing.
    ping_label.config(text=f"Ping: {ping_val} cm  Heading: {heading_val}")
    

def append_scan_data(scan_data_string, is_mock_data=False):
    """ Parses scan data string (expecting DIST_CM) and appends tuple to buffer. """
    global current_scan_buffer
    try:
        angle_deg, dist_cm, ir_raw = None, None, None # Initialize
        if is_mock_data: # Handle mock data if needed (assuming format: angle dist_m)
             parts = scan_data_string.split()
             if len(parts) >= 2:
                 angle_deg = float(parts[0])
                 dist_m = float(parts[1])
                 dist_cm = dist_m * 100.0 # Convert mock meters to cm
                 ir_raw = 0 # Mock IR
        else: # Parsing REAL CyBot data (Expecting DIST_CM now)
            parts = scan_data_string.split(',')
            for part in parts:
                key_value = part.split('=')
                if len(key_value) == 2:
                    key, value = key_value[0].strip(), key_value[1].strip()
                    if key == "ANGLE":
                        angle_deg = float(value)
                    elif key == "DIST_CM": 
                        dist_cm = float(value) 
                    elif key == "IR_RAW":
                        ir_raw = int(value)

        if angle_deg is not None and dist_cm is not None and ir_raw is not None:
             current_scan_buffer.append((angle_deg, dist_cm, ir_raw))
        # else: # Optional: Add print if parsing failed
        #     print(f"Incomplete scan data parsed: Angle={angle_deg}, Dist_CM={dist_cm}, IR={ir_raw} from '{scan_data_string}'")

    except ValueError as ve:
        print(f"ValueError converting scan data '{scan_data_string}': {ve}")
    except Exception as e:
        print(f"Error appending scan data '{scan_data_string}': {e}")

def update_map_with_scan(scan_data_string): # Placeholder, not actively used for object plotting currently
    pass 

# ---vvv--- MODIFIED detect_and_plot_objects FUNCTION ---vvv---
def detect_and_plot_objects(scan_data=None):
    """Processes scan data, finds object edges using IR, uses PING for geometry,
       and plots them with adjusted distance representation."""
    global robot_x, robot_y, robot_angle_deg, last_scan_data, map_canvas
    global MAP_SCALE, SENSOR_FORWARD_OFFSET_CM, OBJECT_MAX_DIST_CM
    global OBJECT_MIN_POINTS, OBJECT_MIN_ANGLE_WIDTH_DEG
    # Using new IR constants:
    global IR_MIN_STRENGTH_FOR_CONSIDERATION, IR_EDGE_THRESHOLD_RISE, IR_EDGE_THRESHOLD_DROP, DEBUG_OBJECT_DETECTION

    if scan_data is None: scan_data = last_scan_data

    map_canvas.delete("detected_object")
    if not scan_data:
        if DEBUG_OBJECT_DETECTION: print("detect_and_plot_objects: No scan data to process.")
        return

    scan_data_sorted = sorted(scan_data, key=lambda p: p[0])

    objects_segments = []
    current_segment_points = []
    in_object_segment = False # State: True if currently collecting points for an object

    # Pad with dummy points to correctly handle edges at the start/end of scan.
    # These dummy points should have IR values that won't trigger edges with real data.
    dummy_ir_weak = min(IR_MIN_STRENGTH_FOR_CONSIDERATION / 2, 50) # Ensure it's weaker than consideration threshold
    dummy_ping_far = OBJECT_MAX_DIST_CM * 3 # Ensure it's beyond relevant PING distance
    
    # Create a list of (angle, dist_cm, ir_raw, prev_ir_raw) for easier iteration
    # The first point's prev_ir_raw will be the dummy_ir_weak.
    processed_scan = []
    if scan_data_sorted:
        processed_scan.append(
            (scan_data_sorted[0][0], scan_data_sorted[0][1], scan_data_sorted[0][2], dummy_ir_weak) 
        )
        for i in range(1, len(scan_data_sorted)):
            processed_scan.append(
                (scan_data_sorted[i][0], scan_data_sorted[i][1], scan_data_sorted[i][2], scan_data_sorted[i-1][2])
            )
    
    # If using padding (can be complex to manage prev_ir correctly with simple padding):
    # For simplicity, this revised version will not use the complex dummy padding from before,
    # but will rely on careful boundary checks or accepting that objects at 0/180 deg might be harder to detect perfectly.
    # Let's proceed by iterating through the sorted, unpadded scan data and managing previous values carefully.

    if DEBUG_OBJECT_DETECTION: print(f"\n--- Starting Object Detection Cycle ({len(scan_data_sorted)} points) ---")
    if DEBUG_OBJECT_DETECTION: 
        print(f"Params: IR_MIN_CONSIDER={IR_MIN_STRENGTH_FOR_CONSIDERATION}, IR_RISE_THRESH={IR_EDGE_THRESHOLD_RISE}, IR_DROP_THRESH={IR_EDGE_THRESHOLD_DROP}")

    prev_ir_raw_val = dummy_ir_weak # Initialize prev_ir_raw for the very first point
    prev_dist_cm_val = dummy_ping_far
    prev_angle_val = -1.0 # Dummy angle

    for i in range(len(scan_data_sorted)):
        angle, dist_cm, ir_raw = scan_data_sorted[i]

        # For the first point, prev_ir_raw_val is dummy_ir_weak. For others, it's the actual previous.
        # This loop structure means prev_ir_raw_val is from the actual scan_data_sorted[i-1] after the first iteration.
        if i > 0:
            prev_ir_raw_val = scan_data_sorted[i-1][2]
            # prev_dist_cm_val = scan_data_sorted[i-1][1] # Not directly used in edge logic but good for context
            # prev_angle_val = scan_data_sorted[i-1][0]

        ir_change = ir_raw - prev_ir_raw_val # current - previous
        
        ping_is_relevant = (dist_cm > 0 and dist_cm <= OBJECT_MAX_DIST_CM)
        current_ir_is_strong = (ir_raw >= IR_MIN_STRENGTH_FOR_CONSIDERATION)
        prev_ir_was_strong = (prev_ir_raw_val >= IR_MIN_STRENGTH_FOR_CONSIDERATION)

        if DEBUG_OBJECT_DETECTION and i < 5: # Print first few points for detail
             print(f"  Point {i}: Angle={angle:.1f}, Dist={dist_cm:.1f}, IR={ir_raw} (PrevIR={prev_ir_raw_val}, Change={ir_change})")
             print(f"     RelevantPING={ping_is_relevant}, CurrStrongIR={current_ir_is_strong}, PrevStrongIR={prev_ir_was_strong}")


        if not in_object_segment:
            # --- Condition to START a new object segment ---
            # Must have relevant PING distance and current IR must be strong enough
            if ping_is_relevant and current_ir_is_strong:
                # Start if EITHER a sharp rise in IR OR a transition from weak IR to strong IR
                is_sharp_rise = (ir_change >= IR_EDGE_THRESHOLD_RISE)
                is_transition_to_strong = (not prev_ir_was_strong) # current_ir_is_strong is already true here

                if is_sharp_rise or is_transition_to_strong:
                    in_object_segment = True
                    current_segment_points = [(angle, dist_cm, ir_raw)]
                    if DEBUG_OBJECT_DETECTION:
                        print(f"  Segment START: Angle={angle:.1f}, IR={ir_raw}, Dist={dist_cm:.1f}. Rise={is_sharp_rise}, Trans={is_transition_to_strong}. Change={ir_change}")
                # else:
                    # if DEBUG_OBJECT_DETECTION and current_ir_is_strong : print(f"    No Start: Angle={angle:.1f}, IR={ir_raw}. Not sharp/transition. Change={ir_change}")

        else: # We are currently in an object segment
            # --- Conditions to END the current object segment ---
            # 1. Current point's PING distance or IR strength makes it unsuitable for continuing
            point_is_unsuitable = not (ping_is_relevant and current_ir_is_strong)
            
            # 2. Sharp drop in IR (current is weaker than previous by a threshold),
            #    AND both current and previous points were considered strong enough to form part of a valid edge.
            #    (Avoids ending due to noise if previous point was already weak).
            #    ir_change = current - prev. So, prev - current = -ir_change
            is_sharp_drop = (current_ir_is_strong and prev_ir_was_strong and (-ir_change >= IR_EDGE_THRESHOLD_DROP) )
            # Alternative for sharp drop: (prev_ir_raw_val - ir_raw >= IR_EDGE_THRESHOLD_DROP)

            if point_is_unsuitable or is_sharp_drop:
                in_object_segment = False
                if len(current_segment_points) >= OBJECT_MIN_POINTS:
                    objects_segments.append(list(current_segment_points))
                    if DEBUG_OBJECT_DETECTION:
                        print(f"  Segment ENDED before Angle={angle:.1f}. Reason: Unsuitable={point_is_unsuitable}, SharpDrop={is_sharp_drop}. PrevIR={prev_ir_raw_val}, CurrIR={ir_raw}")
                        print(f"    Stored segment with {len(current_segment_points)} points. Last point: {current_segment_points[-1][0]:.1f} deg.")
                # else:
                    # if DEBUG_OBJECT_DETECTION: print(f"  Segment Discarded (too few points): {len(current_segment_points)}")
                current_segment_points = []

                # After ending a segment, the current point might be the start of a NEW segment.
                # This logic will be naturally handled when this current point is re-evaluated
                # in the 'if not in_object_segment:' block in the *next iteration* if it wasn't consumed.
                # No, this point needs to be re-evaluated NOW if it caused an end.
                # Let's re-evaluate the *current point* for starting a new segment if it just ended one.
                if ping_is_relevant and current_ir_is_strong:
                    is_sharp_rise = (ir_change >= IR_EDGE_THRESHOLD_RISE)
                    is_transition_to_strong = (not prev_ir_was_strong)
                    if is_sharp_rise or is_transition_to_strong:
                        in_object_segment = True
                        current_segment_points = [(angle, dist_cm, ir_raw)]
                        if DEBUG_OBJECT_DETECTION:
                            print(f"  Segment RE-START immediately at Angle={angle:.1f}, IR={ir_raw}. Rise={is_sharp_rise}, Trans={is_transition_to_strong}")
            else:
                # Continue current segment
                current_segment_points.append((angle, dist_cm, ir_raw))
        
        # Update prev_ir_raw_val for the next iteration is implicitly handled by loop structure for i > 0
        # If we used padding, this would be more complex.

    # Catch any trailing segment after the loop finishes
    if in_object_segment and len(current_segment_points) >= OBJECT_MIN_POINTS:
        objects_segments.append(list(current_segment_points))
        if DEBUG_OBJECT_DETECTION: print(f"  Trailing segment stored with {len(current_segment_points)} points. Last point: {current_segment_points[-1][0]:.1f} deg.")
    
    if DEBUG_OBJECT_DETECTION: print(f"--- Object Detection Cycle END. Found {len(objects_segments)} raw segments. ---")

    # --- Process Segments into Plottable Objects ---
    plotted_objects_info = []
    for idx, segment in enumerate(objects_segments):
        if not segment: continue

        angles = [p[0] for p in segment]
        # Use PING distances from the IR-defined segment for geometry. Filter out invalid PINGs again just in case.
        distances_cm = [p[1] for p in segment if (p[1] > 0 and p[1] <= OBJECT_MAX_DIST_CM)]
        
        if not distances_cm:
            if DEBUG_OBJECT_DETECTION: print(f"  Segment {idx} skipped: No valid PING distances.")
            continue 

        start_angle_obj = angles[0]
        end_angle_obj = angles[-1]
        angular_width_deg = abs(end_angle_obj - start_angle_obj)

        if angular_width_deg < OBJECT_MIN_ANGLE_WIDTH_DEG:
            if DEBUG_OBJECT_DETECTION: print(f"  Segment {idx} skipped: Angular width {angular_width_deg:.1f} < {OBJECT_MIN_ANGLE_WIDTH_DEG:.1f} deg.")
            continue

        # Use PING distances at the segment edges determined by IR
        dist_at_start_angle = segment[0][1] # PING distance for the first point of the IR segment
        dist_at_end_angle = segment[-1][1]  # PING distance for the last point of the IR segment
        
        # Ensure these distances are valid for width calculation
        if not (dist_at_start_angle > 0 and dist_at_start_angle <= OBJECT_MAX_DIST_CM and \
                dist_at_end_angle > 0 and dist_at_end_angle <= OBJECT_MAX_DIST_CM):
            if DEBUG_OBJECT_DETECTION: print(f"  Segment {idx} skipped: Invalid edge PING distances for width calc (Start: {dist_at_start_angle:.1f}, End: {dist_at_end_angle:.1f}).")
            continue
            
        linear_width_cm = 0
        angle_diff_rad = math.radians(angular_width_deg)
        
        # Law of Cosines: c^2 = a^2 + b^2 - 2ab * cos(C)
        # Here, c = linear_width_cm, a = dist_at_start_angle, b = dist_at_end_angle, C = angle_diff_rad
        term_for_sqrt = (dist_at_start_angle**2 + dist_at_end_angle**2 -
                         2 * dist_at_start_angle * dist_at_end_angle * math.cos(angle_diff_rad))
        
        if term_for_sqrt >= 0: # Ensure argument for sqrt is non-negative
            linear_width_cm = math.sqrt(term_for_sqrt)
        else: # Should not happen if angles/distances are sane, but as a fallback
            if DEBUG_OBJECT_DETECTION: print(f"  Segment {idx} Warning: Negative term for sqrt in width calc ({term_for_sqrt:.2f}). Using fallback.")
            # Fallback: Estimate width based on angular span and average distance (less accurate)
            avg_dist_cm = sum(distances_cm) / len(distances_cm)
            linear_width_cm = avg_dist_cm * angle_diff_rad # Arc length approximation

        closest_dist_in_segment_cm = min(distances_cm) # Overall closest PING reading in the segment

        plotted_objects_info.append({
            'middle_angle_servo': (start_angle_obj + end_angle_obj) / 2.0,
            'closest_distance_cm': closest_dist_in_segment_cm,
            'linear_width_cm': linear_width_cm,
            'start_angle': start_angle_obj, # For debug
            'end_angle': end_angle_obj,     # For debug
            'num_points': len(segment)      # For debug
        })
        if DEBUG_OBJECT_DETECTION:
             print(f"  Plotted Object from Segment {idx}: StartAng={start_angle_obj:.1f}, EndAng={end_angle_obj:.1f}, Width={linear_width_cm:.2f}cm, ClosestDist={closest_dist_in_segment_cm:.1f}cm")

    if DEBUG_OBJECT_DETECTION: print(f"--- Found {len(plotted_objects_info)} objects after filtering. ---")

    # --- Calculate Sensor's current position on the map (same as before) ---
    sensor_offset_pixels = SENSOR_FORWARD_OFFSET_CM * MAP_SCALE
    robot_current_angle_rad = math.radians(robot_angle_deg)
    sensor_origin_x = robot_x + sensor_offset_pixels * math.cos(robot_current_angle_rad)
    sensor_origin_y = robot_y - sensor_offset_pixels * math.sin(robot_current_angle_rad)

    # --- Plotting Validated Objects ---
    for obj_info in plotted_objects_info:
        # Basic check, though distances should be positive if they made it this far
        if obj_info['closest_distance_cm'] <= 0 or obj_info['linear_width_cm'] <= 0: continue

        # Object's center angle relative to robot's forward direction (0 degrees for sensor)
        # Servo angles are 0-180. Robot forward is when servo is at 90 deg.
        object_angle_relative_to_robot_forward_deg = obj_info['middle_angle_servo'] - 90.0
        
        # World angle of the line from SENSOR to the CENTER of the object's angular span
        world_angle_of_object_center_deg = robot_angle_deg + object_angle_relative_to_robot_forward_deg
        obj_center_angle_world_rad = math.radians(world_angle_of_object_center_deg)

        # For plotting, place the center of the oval such that its edge touches the closest point
        obj_closest_edge_dist_cm = obj_info['closest_distance_cm'] 
        obj_visual_radius_cm = obj_info['linear_width_cm'] / 2.0

        # Distance from SENSOR to the plotted OVAL's CENTER
        oval_center_dist_from_sensor_cm = obj_closest_edge_dist_cm + obj_visual_radius_cm
        oval_center_dist_pixels = oval_center_dist_from_sensor_cm * MAP_SCALE
        
        # Coordinates of the OVAL's center on the map
        obj_oval_center_x = sensor_origin_x + oval_center_dist_pixels * math.cos(obj_center_angle_world_rad)
        obj_oval_center_y = sensor_origin_y - oval_center_dist_pixels * math.sin(obj_center_angle_world_rad)

        obj_visual_radius_pixels = max(obj_visual_radius_cm * MAP_SCALE, 2.0) # Min 2 pixels radius

        map_canvas.create_oval(obj_oval_center_x - obj_visual_radius_pixels,
                               obj_oval_center_y - obj_visual_radius_pixels,
                               obj_oval_center_x + obj_visual_radius_pixels,
                               obj_oval_center_y + obj_visual_radius_pixels,
                               outline="darkmagenta", fill="orchid", width=2, tags="detected_object")
        
        map_canvas.create_text(obj_oval_center_x, obj_oval_center_y,
                               text=f"{obj_info['closest_distance_cm']:.0f}", 
                               fill="black", font=("Arial", 7), tags="detected_object")
# ---^^^--- END OF MODIFIED detect_and_plot_objects FUNCTION ---^^^---

def update_map_with_bump(bump_info_string):
    """Draws a bump indicator on the map."""
    global robot_x, robot_y, robot_angle_deg
    if DEBUG_OBJECT_DETECTION: print(f"Updating map with bump: {bump_info_string}") # Optional debug
    bump_offset_pixels = ROBOT_RADIUS_PIXELS 
    bump_angle_relative_deg = 0
    if "LEFT" in bump_info_string.upper(): bump_angle_relative_deg = 45 # Sensor is forward, bump is on robot body
    elif "RIGHT" in bump_info_string.upper(): bump_angle_relative_deg = -45

    bump_angle_world_deg = robot_angle_deg + bump_angle_relative_deg # This assumes bump is at robot center + angle
    # More accurately, bump location depends on where on the chassis it is.
    # For simplicity, we draw it relative to robot center and orientation.
    
    bump_angle_world_rad = math.radians(bump_angle_world_deg)

    # Offset from robot center towards the bump direction
    bump_indicator_offset_x = ROBOT_RADIUS_PIXELS * math.cos(bump_angle_world_rad)
    bump_indicator_offset_y = -ROBOT_RADIUS_PIXELS * math.sin(bump_angle_world_rad) # Y decreases upwards

    bump_x = robot_x + bump_indicator_offset_x
    bump_y = robot_y + bump_indicator_offset_y
    radius = 5
    map_canvas.create_rectangle(bump_x - radius, bump_y - radius, bump_x + radius, bump_y + radius,
                                fill="red", outline="darkred", tags="bump_event")

# ---vvv--- MODIFIED FUNCTION (Added Logging from previous responses) ---vvv---
def update_robot_position_and_trail(move_data_string):
    """Updates the robot's pose (x, y, angle) and draws a trail segment."""
    global robot_x, robot_y, robot_angle_deg
    # print(f"--- Pose Update --- Received MOVE data: '{move_data_string}'") 
    try:
        dist_cm, angle_deg_delta = 0.0, 0.0
        parts = move_data_string.split(',')
        for part in parts:
            key_value = part.split('=')
            if len(key_value) == 2:
                key, value = key_value[0].strip(), key_value[1].strip()
                if key == "DIST_CM":
                    dist_cm = float(value)
                elif key == "ANGLE_DEG":
                    angle_deg_delta = float(value)

        # print(f"--- Pose Update --- Parsed: Dist={dist_cm:.2f} cm, Angle Delta={angle_deg_delta:.2f} deg") 

        prev_x, prev_y = robot_x, robot_y
        # prev_angle = robot_angle_deg # Not strictly needed for drawing trail line

        # Update angle FIRST ( Cybot likely reports angle change, then moves forward based on new heading )
        robot_angle_deg += angle_deg_delta
        robot_angle_deg %= 360 
        if robot_angle_deg < 0: robot_angle_deg += 360

        dist_pixels = dist_cm * MAP_SCALE
        # Calculate displacement based on the AVERAGE angle if turn&move happen "together"
        # Or, if turn happens, then move, use NEW angle. Assume new angle for forward motion.
        current_robot_angle_rad = math.radians(robot_angle_deg) 
        
        delta_x = dist_pixels * math.cos(current_robot_angle_rad)
        delta_y = -dist_pixels * math.sin(current_robot_angle_rad) # Y decreases upwards

        robot_x += delta_x
        robot_y += delta_y

        # print(f"--- Pose Update --- Old Pose: ({prev_x:.1f}, {prev_y:.1f}), {prev_angle:.1f} deg")
        # print(f"--- Pose Update --- New Pose: ({robot_x:.1f}, {robot_y:.1f}), {robot_angle_deg:.1f} deg")

        if abs(dist_cm) > 0.1 or abs(angle_deg_delta) > 0.1: # If significant movement
             map_canvas.create_line(prev_x, prev_y, robot_x, robot_y, fill="darkgreen", width=2, tags="trail")

        draw_robot_on_map()
    except ValueError as ve:
        print(f"ValueError processing move data '{move_data_string}': {ve}")
    except Exception as e:
        print(f"Error processing move data '{move_data_string}': {e}")
# ---^^^--- MODIFIED FUNCTION ---^^^---


# (draw_radar_plot, clear_map_features, draw_robot_on_map functions remain the same)
# In GUI.py

# (Make sure math is imported: import math)

def draw_radar_plot():
    """Draws the radar grid, last PING scan (red), and last IR scan (blue)."""
    global last_scan_data, radar_canvas # Ensure radar_canvas is accessible
    # print(f"\nAttempting to draw radar. Points available: {len(last_scan_data)}") # Optional debug log
    radar_canvas.delete("all") # Clear everything first (grid, plots, robot icon)

    if not last_scan_data:
        # print("Radar draw skipped: last_scan_data is empty.") # Optional debug log
        return

    try:
        canvas_width = radar_canvas.winfo_width()
        canvas_height = radar_canvas.winfo_height()
    except tk.TclError: # Happens if canvas isn't fully initialized yet
        # print("Radar canvas not ready, retrying draw...")
        app.after(50, draw_radar_plot) # Retry shortly
        return

    if canvas_width <= 1 or canvas_height <= 1: # Canvas not properly sized yet
        # print("Radar canvas too small, skipping draw.")
        return

    center_x = canvas_width / 2
    center_y = canvas_height # Base Y at the bottom for a 180-degree forward sweep
    max_radius_pixels = min(canvas_width / 2.0, canvas_height) * 0.9 # Max plot radius to fit nicely

    # Use the same max distance for the PING plot scale and grid
    max_dist_cm_for_plot = 330.0 # Max range for PING display and grid lines (e.g. 3.3 meters)

    # --- Draw Grid (scaled to max_dist_cm_for_plot) ---
    grid_color = "#A0A0A0"; label_color = "#505050"
    # Grid arcs (semi-circles)
    for r_cm in [50, 100, 150, 200, 250, 300]: # Define distances for grid lines
        if r_cm > max_dist_cm_for_plot : continue
        r_ratio = r_cm / max_dist_cm_for_plot
        r_pixels = max_radius_pixels * r_ratio
        
        if all(map(math.isfinite, [center_x - r_pixels, center_y - r_pixels, center_x + r_pixels, center_y + r_pixels])):
            radar_canvas.create_arc(center_x - r_pixels, center_y - r_pixels, center_x + r_pixels, center_y + r_pixels,
                                    start=0, extent=180, outline=grid_color, style=tk.ARC, tags="scan_plot_grid")
            text_r_pixels = r_pixels + 2 # Place text slightly outside the arc
            if math.isfinite(center_x + 5) and math.isfinite(center_y - text_r_pixels + 8):
                 radar_canvas.create_text(center_x + 5, center_y - text_r_pixels + 8, text=f"{r_cm:.0f}", fill=label_color, font=("Arial", 7), anchor="w", tags="scan_plot_grid")

    # Radial lines (for angles)
    for angle_deg_servo_frame in range(0, 181, 30): # 0 to 180 degrees in servo frame
        # Plot angle is directly the servo angle (0 right, 90 forward, 180 left for radar display)
        plot_angle_rad = math.radians(angle_deg_servo_frame) 
        line_end_x = center_x + max_radius_pixels * math.cos(plot_angle_rad)
        line_end_y = center_y - max_radius_pixels * math.sin(plot_angle_rad) # Y decreases upwards
        
        if all(map(math.isfinite, [center_x, center_y, line_end_x, line_end_y])):
            radar_canvas.create_line(center_x, center_y, line_end_x, line_end_y, fill=grid_color, tags="scan_plot_grid")

        # Angle Labels
        label_rad_offset = max_radius_pixels * 1.05 # Place labels slightly beyond max radius
        label_x = center_x + label_rad_offset * math.cos(plot_angle_rad)
        label_y = center_y - label_rad_offset * math.sin(plot_angle_rad)
        
        anchor_pos = tk.CENTER; x_offset = 0; y_offset = 0 # Default anchor
        if angle_deg_servo_frame == 0: anchor_pos = tk.W; x_offset = 3
        elif angle_deg_servo_frame == 180: anchor_pos = tk.E; x_offset = -3
        elif angle_deg_servo_frame == 90: anchor_pos = tk.S; y_offset = -3 # Below point for 90 deg
        elif angle_deg_servo_frame > 90: # Top-left quadrant of radar
            anchor_pos = tk.NE if angle_deg_servo_frame < 135 else tk.E ; y_offset = 1; x_offset = -1
        elif angle_deg_servo_frame < 90: # Top-right quadrant of radar
            anchor_pos = tk.NW if angle_deg_servo_frame > 45 else tk.W; y_offset = 1; x_offset = 1
            
        if all(map(math.isfinite, [label_x + x_offset, label_y + y_offset])):
             radar_canvas.create_text(label_x + x_offset, label_y + y_offset, text=f"{angle_deg_servo_frame}°", fill=label_color, font=("Arial", 8), anchor=anchor_pos, tags="scan_plot_grid")

    # --- Draw Robot Icon at the center base of the radar ---
    robot_icon_size = 5
    if all(map(math.isfinite, [center_x - robot_icon_size, center_y - robot_icon_size, center_x + robot_icon_size, center_y])): # Check validity
        radar_canvas.create_oval(center_x - robot_icon_size, center_y - robot_icon_size, # Small circle for robot base
                                 center_x + robot_icon_size, center_y, 
                                 fill="darkgreen", outline="black", tags="radar_robot")
        radar_canvas.create_line(center_x, center_y, center_x, center_y - robot_icon_size * 1.5, # Line for robot orientation (straight up for 90 deg)
                                 fill="white", width=1, arrow=tk.LAST, tags="radar_robot")

    # --- Prepare to Plot Scan Data ---
    ping_points_pixels = [] # Holds (x, y) for PING line segments
    ir_points_pixels = []   # Holds (x, y) for IR line segments
    # num_ping_plotted = 0; num_ir_plotted = 0; num_ir_skipped = 0 # For debug

    # --- Loop through scan data (angle_deg, dist_cm, ir_raw) ---
    for angle_deg_servo_frame, dist_cm, ir_raw in last_scan_data:
        # Angle for plotting on radar (0-180 deg servo frame)
        plot_angle_rad = math.radians(angle_deg_servo_frame)
        valid_ping_point_for_current_segment = False
        valid_ir_point_for_current_segment = False

        # --- Process PING Data (Red Line) ---
        if dist_cm > 0 and dist_cm <= max_dist_cm_for_plot:
            ping_plot_radius_pixels = (dist_cm / max_dist_cm_for_plot) * max_radius_pixels
            ping_point_x = center_x + ping_plot_radius_pixels * math.cos(plot_angle_rad)
            ping_point_y = center_y - ping_plot_radius_pixels * math.sin(plot_angle_rad)

            if math.isfinite(ping_point_x) and math.isfinite(ping_point_y):
                ping_points_pixels.extend([ping_point_x, ping_point_y])
                valid_ping_point_for_current_segment = True
                # num_ping_plotted +=1
            # else: print(f"Invalid PING coordinate: angle={angle_deg_servo_frame}, dist={dist_cm}")
        
        # If current PING point is invalid (or too far), break the line segment
        if not valid_ping_point_for_current_segment and len(ping_points_pixels) >= 4: # Need at least 2 points (4 coords)
            try: radar_canvas.create_line(ping_points_pixels, fill="red", width=2, tags="ping_scan_plot")
            except Exception as e: print(f"Error drawing PING line segment (invalid point): {e}")
            ping_points_pixels = [] # Reset for next segment

        # --- Process IR Data (Blue Line) ---
        # IR_VALID_MIN, IR_MIN_RAW, IR_MAX_RAW are for radar visualization tuning
        if ir_raw >= IR_VALID_MIN: 
            clamped_ir = max(IR_MIN_RAW, min(ir_raw, IR_MAX_RAW)) # Clamp to expected range
            # Normalize: higher IR (closer object) -> norm_ir near 1; lower IR (further) -> norm_ir near 0
            norm_ir = (clamped_ir - IR_MIN_RAW) / (IR_MAX_RAW - IR_MIN_RAW) 
            # Invert for plotting: closer (high IR, norm_ir near 1) -> smaller radius on radar
            ir_plot_radius_pixels = (1.0 - norm_ir) * max_radius_pixels 
            # Ensure radius is not negative if normalization is off
            ir_plot_radius_pixels = max(0, ir_plot_radius_pixels)


            ir_point_x = center_x + ir_plot_radius_pixels * math.cos(plot_angle_rad)
            ir_point_y = center_y - ir_plot_radius_pixels * math.sin(plot_angle_rad)

            if math.isfinite(ir_point_x) and math.isfinite(ir_point_y):
                ir_points_pixels.extend([ir_point_x, ir_point_y])
                valid_ir_point_for_current_segment = True
                # num_ir_plotted += 1
            # else: print(f"Invalid IR coordinate: angle={angle_deg_servo_frame}, ir_raw={ir_raw}")
        # else: num_ir_skipped +=1
            
        # If current IR point is invalid (or too low), break the line segment
        if not valid_ir_point_for_current_segment and len(ir_points_pixels) >= 4: # Need at least 2 points
            try: radar_canvas.create_line(ir_points_pixels, fill="blue", width=2, tags="ir_scan_plot")
            except Exception as e: print(f"Error drawing IR line segment (invalid point): {e}")
            ir_points_pixels = [] # Reset for next segment

    # --- Draw the final PING and IR segments after the loop ---
    if len(ping_points_pixels) >= 4:
        try: radar_canvas.create_line(ping_points_pixels, fill="red", width=2, tags="ping_scan_plot")
        except Exception as e: print(f"Error drawing final PING line segment: {e}")
    if len(ir_points_pixels) >= 4:
        try: radar_canvas.create_line(ir_points_pixels, fill="blue", width=2, tags="ir_scan_plot")
        except Exception as e: print(f"Error drawing final IR line segment: {e}")
        
    # print(f"Radar Draw Complete. PING Plotted: {num_ping_plotted}, IR Plotted: {num_ir_plotted}, IR Skipped: {num_ir_skipped}")


def clear_map_features(tag_to_clear):
    """Clears specific features (trail, objects, bumps) from the map."""
    map_canvas.delete(tag_to_clear)
    if tag_to_clear == "trail": # If clearing trail, re-center robot representation
        # This assumes robot hasn't actually moved, just clearing drawing.
        # If robot *has* moved, this re-initialization of position might be confusing.
        # Consider if re-drawing robot is always needed or only on full map reset.
        # For now, let's assume it implies a visual reset, so re-drawing robot at current (x,y) is fine.
        draw_robot_on_map() # Redraw robot after clearing trail (it might have been covered)
        initialize_robot_position() # This would reset robot_x, robot_y to map center. Usually not what's wanted when clearing trail.


def draw_robot_on_map(event=None): # event=None allows binding to <Configure>
    """Draws the robot icon (circle) on the map canvas at its current pose."""
    global robot_x, robot_y, robot_angle_deg, map_canvas, MAP_SCALE 
    map_canvas.delete("robot") 

    # Only draw if connected or if robot has a valid position (e.g. from previous session/load)
    # For this GUI, it's mainly about when connected.
    if not is_connected and not (robot_x > 0 and robot_y > 0 and map_canvas.winfo_width() > 1): 
        # print("Skip drawing robot: Not connected or invalid initial state.")
        return

    # ROBOT_REAL_RADIUS_CM is the physical radius, used for visual representation scaled by MAP_SCALE
    radius_pixels = ROBOT_REAL_RADIUS_CM * MAP_SCALE

    cx, cy = robot_x, robot_y

    x1 = cx - radius_pixels
    y1 = cy - radius_pixels
    x2 = cx + radius_pixels
    y2 = cy + radius_pixels

    if all(map(math.isfinite, [x1, y1, x2, y2])):
        map_canvas.create_oval(x1, y1, x2, y2,
                                  fill="darkblue", outline="black", width=1, tags="robot")

        # Draw a line to indicate orientation (from center to edge in direction of robot_angle_deg)
        angle_rad = math.radians(robot_angle_deg) # Convert current robot angle to radians
        line_end_x = cx + radius_pixels * math.cos(angle_rad)
        line_end_y = cy - radius_pixels * math.sin(angle_rad) # Y decreases upwards in Tkinter canvas

        if all(map(math.isfinite, [line_end_x, line_end_y])):
             map_canvas.create_line(cx, cy, line_end_x, line_end_y,
                                     fill="white", width=2, tags="robot")
    # else:
        # print(f"Warning: Invalid coordinates for robot drawing at ({cx}, {cy}), angle {robot_angle_deg}")


# --- GUI Setup ---
# (GUI setup code remains the same)
app = tk.Tk()
app.title("CyBot Control Center - Ice Cream Truck")
app.geometry("1000x750") # Initial size
app.minsize(800, 600) # Minimum window size
style = ttk.Style(); style.theme_use('clam') # Use a theme

# Connection Frame
connection_frame = ttk.LabelFrame(app, text="Connection"); connection_frame.pack(pady=5, padx=10, fill="x")
status_label = ttk.Label(connection_frame, text="Disconnected", foreground="red", font=("Arial", 10, "bold")); status_label.pack(side=tk.LEFT, padx=5, pady=5)
connect_button = ttk.Button(connection_frame, text="Connect", command=connect_to_cybot); connect_button.pack(side=tk.LEFT, padx=5, pady=5)
disconnect_button = ttk.Button(connection_frame, text="Disconnect", command=disconnect_from_cybot, state=tk.DISABLED); disconnect_button.pack(side=tk.LEFT, padx=5, pady=5)

# Control Buttons Frame
control_frame = ttk.LabelFrame(app, text="Controls"); control_frame.pack(pady=5, padx=10, fill="x")
scan_button = ttk.Button(control_frame, text="Scan (m)", command=lambda: send_command(CMD_SCAN), state=tk.DISABLED); scan_button.pack(side=tk.LEFT, padx=5, pady=5)
jingle_button = ttk.Button(control_frame, text="Jingle (j)", command=lambda: send_command(CMD_JINGLE), state=tk.DISABLED); jingle_button.pack(side=tk.LEFT, padx=5, pady=5)
ttk.Label(control_frame, text="Movement: Use WASD keys").pack(side=tk.LEFT, padx=20)

# Main Paned Window (Resizable Split)
paned_window = ttk.PanedWindow(app, orient=tk.HORIZONTAL); paned_window.pack(pady=10, padx=10, expand=True, fill="both")

# --- Left Pane ---
left_pane_frame = ttk.Frame(paned_window, width=400); paned_window.add(left_pane_frame, weight=1) # Adjust weight as needed

# Raw Data Log (Takes up most of left pane)
raw_data_frame = ttk.LabelFrame(left_pane_frame, text="Raw Data Log"); raw_data_frame.pack(pady=5, padx=5, expand=True, fill="both")
raw_data_text = scrolledtext.ScrolledText(raw_data_frame, wrap=tk.WORD, height=15, width=45, font=("Consolas", 9)); raw_data_text.pack(expand=True, fill="both")

# Bottom Left Frame (Holds Sensor Status and Radar)
bottom_left_frame = ttk.Frame(left_pane_frame); bottom_left_frame.pack(pady=5, padx=5, fill="x", side=tk.BOTTOM)

# Sensor Status Frame (Parent for Canvas and Labels)
sensor_frame = ttk.LabelFrame(bottom_left_frame, text="Sensor Status"); sensor_frame.pack(side=tk.LEFT, padx=(0, 5), fill="y", anchor='nw') # Anchor top-left
sensor_canvas = tk.Canvas(sensor_frame, width=200, height=200, bg="white", highlightthickness=1, highlightbackground="grey")
sensor_canvas.pack(pady=5, anchor='n') # Pack the canvas first, anchor top
sensor_canvas.create_oval(50, 50, 150, 150, outline="black", width=2, tags="base_robot_shape") # Main body
sensor_canvas.create_rectangle(90, 35, 110, 50, outline="black", width=2, tags="base_robot_shape") # Turret
sensor_canvas.create_oval(65, 55, 75, 65, fill="grey", outline="black", tags="cliff_l_indicator")  # Left
sensor_canvas.create_oval(85, 45, 95, 55, fill="grey", outline="black", tags="cliff_fl_indicator") # Front Left
sensor_canvas.create_oval(105, 45, 115, 55, fill="grey", outline="black", tags="cliff_fr_indicator")# Front Right
sensor_canvas.create_oval(125, 55, 135, 65, fill="grey", outline="black", tags="cliff_r_indicator") # Right
cliff_signal_frame = ttk.Frame(sensor_frame)
cliff_signal_frame.pack(pady=(0, 2), anchor='n') # Pack below canvas, anchor top
cliff_l_sig_label = ttk.Label(cliff_signal_frame, text="L: N/A", width=7, anchor="center"); cliff_l_sig_label.pack(side=tk.LEFT, padx=1)
cliff_fl_sig_label = ttk.Label(cliff_signal_frame, text="FL: N/A", width=7, anchor="center"); cliff_fl_sig_label.pack(side=tk.LEFT, padx=1)
cliff_fr_sig_label = ttk.Label(cliff_signal_frame, text="FR: N/A", width=7, anchor="center"); cliff_fr_sig_label.pack(side=tk.LEFT, padx=1)
cliff_r_sig_label = ttk.Label(cliff_signal_frame, text="R: N/A", width=7, anchor="center"); cliff_r_sig_label.pack(side=tk.LEFT, padx=1)
ping_label = ttk.Label(sensor_frame, text="Ping: N/A", anchor="center")
ping_label.pack(pady=(2, 5), anchor='n') # Pack below cliff frame, anchor top

# Radar Frame
radar_frame = ttk.LabelFrame(bottom_left_frame, text="Last Scan Radar"); radar_frame.pack(side=tk.LEFT, padx=(5, 0), expand=True, fill="both")
radar_canvas = tk.Canvas(radar_frame, bg="#d0d0e0", highlightthickness=1, highlightbackground="grey"); radar_canvas.pack(expand=True, fill="both", pady=5, padx=5)
radar_canvas.bind("<Configure>", lambda e: app.after(50, draw_radar_plot)) # Redraw radar on resize, with a small delay
clear_radar_button = ttk.Button(radar_frame, text="Clear Radar", command=lambda: radar_canvas.delete("ping_scan_plot", "ir_scan_plot")); clear_radar_button.pack(side=tk.BOTTOM, pady=2)


# --- Right Pane ---
map_frame = ttk.LabelFrame(paned_window, text="Test Field Map (Top-Down View)"); paned_window.add(map_frame, weight=3) # Give it more weight
map_canvas = tk.Canvas(map_frame, bg="lightgrey", highlightthickness=1, highlightbackground="grey"); map_canvas.pack(expand=True, fill="both")
map_canvas.bind("<Configure>", lambda e: app.after(50, draw_robot_on_map)) # Redraw robot if canvas size changes, with a small delay
map_button_frame = ttk.Frame(map_frame); map_button_frame.pack(side=tk.BOTTOM, fill="x", pady=2)
clear_objects_button = ttk.Button(map_button_frame, text="Clear Objects", command=lambda: clear_map_features("detected_object")); clear_objects_button.pack(side=tk.LEFT, padx=5)
clear_bump_button = ttk.Button(map_button_frame, text="Clear Bump Events", command=lambda: clear_map_features("bump_event")); clear_bump_button.pack(side=tk.LEFT, padx=5)
clear_trail_button = ttk.Button(map_button_frame, text="Clear Trail", command=lambda: clear_map_features("trail")); clear_trail_button.pack(side=tk.LEFT, padx=5)


# --- Initialization and Main Loop ---
# (on_closing function and app.mainloop() remain the same)
def on_closing():
    """Handles window close event."""
    if messagebox.askokcancel("Quit", "Do you want to quit?"):
        disconnect_from_cybot() # Attempt graceful disconnect
        stop_thread_flag.set() # Signal listening thread to stop
        app.after(200, app.destroy) # Give a moment for threads to close before destroying app

app.protocol("WM_DELETE_WINDOW", on_closing)
unbind_keys() # Ensure keys are unbound at start if not connected

try:
    # Initial dummy update to populate sensor status display
    update_sensor_status("BUMP_L=0,BUMP_R=0,CLIFF_L_SIG=0,CLIFF_FL_SIG=0,CLIFF_FR_SIG=0,CLIFF_R_SIG=0,PING=0.0")
    # Initial draw of radar (will be empty) and map (robot might not be centered if not connected)
    app.after(100, draw_radar_plot) # Delay to allow canvas to initialize
    app.after(100, initialize_robot_position) # Try to center robot after canvas is up
except Exception as e:
    print(f"ERROR during initial GUI update: {e}")
    messagebox.showerror("Startup Error", f"An error occurred during initial GUI setup:\n{e}")

app.mainloop()

# --- Cleanup ---
print("Application closing.")
stop_thread_flag.set() # Final attempt to ensure thread stops