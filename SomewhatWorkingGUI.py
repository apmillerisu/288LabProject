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
CMD_RIGHT = "d\n"
CMD_SCAN = "m\n"
CMD_JINGLE = "j\n"
CMD_IGNORE = "l\n"

# Map and Trail Constants
MAP_SCALE = 2.0 # pixels / cm (e.g., 1 meter = 100 cm = 200 pixels)
ROBOT_RADIUS_PIXELS = 15 # Approximate visual size on map
ROBOT_REAL_RADIUS_CM = 33.0
SENSOR_FORWARD_OFFSET_CM = 30.0 # Distance sensor is forward from robot center (e.g., 30cm). Adjust as needed.

# Object Detection Constants (Tune these)
OBJECT_MAX_DIST_CM = 250.0 # Ignore points further than this for object detection
OBJECT_MIN_ANGLE_WIDTH_DEG = 6.0 # Minimum angular size to be considered an object
OBJECT_MIN_POINTS = 3 # Minimum consecutive points to form an object
# ---vvv--- LOWERED THRESHOLD ---vvv---
OBJECT_EDGE_THRESHOLD_CM = 15.0 # Min distance change (cm) to detect edge (Lowered from 30)
IR_EDGE_THRESHOLD = 300
# --- Add these near other constants ---
IR_MIN_RAW = 500.0  # Raw value considered "far" for plotting
IR_MAX_RAW = 2500.0 # Raw value considered "close" for plotting
IR_VALID_MIN = 100   # Minimum raw value to consider plotting (avoids plotting noise)
IR_MIN_STRENGTH_FOR_CONSIDERATION = 650 # New: Minimum average IR value to consider a PING segment a plotted object. Tune this!
# ---^^^--- LOWERED THRESHOLD ---^^^---


# Cliff Color Thresholds
WHITE_THRESHOLD = 3000
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
        elif key == 'd': send_command(CMD_RIGHT)
        elif key == 'm': send_command(CMD_SCAN)
        elif key == 'j': send_command(CMD_JINGLE)
        elif key == 'l': send_command(CMD_IGNORE)

def bind_keys():
    """Binds WASD, M, J keys to the handler."""
    print("Binding keys...")
    app.bind_all('<KeyPress-w>', handle_keypress)
    app.bind_all('<KeyPress-s>', handle_keypress)
    app.bind_all('<KeyPress-a>', handle_keypress)
    app.bind_all('<KeyPress-d>', handle_keypress)
    app.bind_all('<KeyPress-m>', handle_keypress)
    app.bind_all('<KeyPress-j>', handle_keypress)
    app.bind_all('<KeyPress-l>', handle_keypress)

def unbind_keys():
    """Unbinds control keys."""
    print("Unbinding keys...")
    app.unbind_all('<KeyPress-w>')
    app.unbind_all('<KeyPress-s>')
    app.unbind_all('<KeyPress-a>')
    app.unbind_all('<KeyPress-d>')
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
            print(f"\nScan END marker received: '{line}'") # Simplified print
            print(f"Buffer size BEFORE processing END: {len(current_scan_buffer)}")
            if current_scan_buffer:
                last_scan_data = current_scan_buffer[:]
                current_scan_buffer = []
                print(f"Copied data to last_scan_data (size: {len(last_scan_data)}). Cleared buffer.")
                # Use app.after to ensure GUI updates happen safely in the main thread
                app.after(10, draw_radar_plot) # Schedule radar plot
                app.after(20, detect_and_plot_objects) # Schedule object detection
            else:
                print("Scan END received, but current_scan_buffer is empty. No plotting.")
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
#  update_map_with_scan, detect_and_plot_objects, update_map_with_bump
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

    except Exception as e:
        print(f"Error parsing status string '{status_string}': {e}")
        cliff_l_sig_val_str, cliff_fl_sig_val_str, cliff_fr_sig_val_str, cliff_r_sig_val_str = "Err", "Err", "Err", "Err"
        ping_val = "Err"
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
    ping_label.config(text=f"Ping: {ping_val} cm")

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
                 ir_raw = 0
        else: # Parsing REAL CyBot data (Expecting DIST_CM now)
            parts = scan_data_string.split(',')
            for part in parts:
                key_value = part.split('=')
                if len(key_value) == 2:
                    key, value = key_value[0].strip(), key_value[1].strip()
                    if key == "ANGLE":
                        angle_deg = float(value)
                    elif key == "DIST_CM": # <<< LOOK FOR DIST_CM
                        dist_cm = float(value) # <<< NO division by 10
                    elif key == "IR_RAW":
                        ir_raw = int(value)

        # Check if all necessary values were successfully parsed
        if angle_deg is not None and dist_cm is not None and ir_raw is not None:
             current_scan_buffer.append((angle_deg, dist_cm, ir_raw))
        # else: # Optional: Add print if parsing failed
        #     print(f"Incomplete scan data parsed: Angle={angle_deg}, Dist_CM={dist_cm}, IR={ir_raw} from '{scan_data_string}'")

    except ValueError as ve:
        print(f"ValueError converting scan data '{scan_data_string}': {ve}")
    except Exception as e:
        print(f"Error appending scan data '{scan_data_string}': {e}")

def update_map_with_scan(scan_data_string):
    pass # Placeholder

# (Ensure math, global variables like robot_x, etc., and constants are accessible)

def detect_and_plot_objects(scan_data=None):
    """Processes scan data, finds object edges using IR, uses PING for geometry,
       and plots them with adjusted distance representation."""
    global robot_x, robot_y, robot_angle_deg, last_scan_data, map_canvas
    global MAP_SCALE, SENSOR_FORWARD_OFFSET_CM, OBJECT_MAX_DIST_CM
    global OBJECT_MIN_POINTS, OBJECT_MIN_ANGLE_WIDTH_DEG # Existing utility thresholds
    global IR_EDGE_THRESHOLD, IR_MIN_STRENGTH_FOR_CONSIDERATION # New IR detection constants

    if scan_data is None: scan_data = last_scan_data

    map_canvas.delete("detected_object")
    if not scan_data:
        return

    # Assuming scan_data is a list of (angle_deg, dist_cm, ir_raw)
    # Sort by angle for consistent processing, if not already sorted
    scan_data_sorted = sorted(scan_data, key=lambda p: p[0])

    objects_segments = []  # Stores segments of (angle, dist_cm, ir_raw) points
    current_segment_points = []
    in_object_segment = False

    # Pad with dummy points to correctly handle edges at the start/end of scan.
    # Dummy points should have IR values that won't trigger edges with real data.
    dummy_ir_far = min(IR_MIN_STRENGTH_FOR_CONSIDERATION / 2, 200) # Weak IR
    dummy_ping_far = OBJECT_MAX_DIST_CM * 3
    scan_data_padded = \
        [(-5.0, dummy_ping_far, dummy_ir_far)] + \
        scan_data_sorted + \
        [(185.0, dummy_ping_far, dummy_ir_far)]

    for i in range(1, len(scan_data_padded)):
        angle, dist_cm, ir_raw = scan_data_padded[i]
        prev_angle, prev_dist_cm, prev_ir_raw = scan_data_padded[i-1]

        ir_change = ir_raw - prev_ir_raw

        # Conditions for the current point to be viable for object detection
        ping_is_relevant = (dist_cm > 0 and dist_cm <= OBJECT_MAX_DIST_CM)
        current_ir_is_strong_enough = (ir_raw >= IR_MIN_STRENGTH_FOR_CONSIDERATION)
        prev_ir_is_strong_enough = (prev_ir_raw >= IR_MIN_STRENGTH_FOR_CONSIDERATION) # For transition detection

        if not in_object_segment:
            # START Condition:
            # 1. PING must be in a relevant range.
            # 2. Current IR reading must be strong enough.
            # 3. Either:
            #    a. Significant IR increase (sharp edge).
            #    b. OR, IR just transitioned from "not strong enough" to "strong enough".
            if ping_is_relevant and current_ir_is_strong_enough and \
               (ir_change >= IR_EDGE_THRESHOLD or \
                (not prev_ir_is_strong_enough)): # Transitioned into strong IR
                in_object_segment = True
                current_segment_points = [(angle, dist_cm, ir_raw)]
        else:  # in_object_segment
            # END Condition:
            # Segment ends if:
            # 1. PING is no longer relevant (e.g., object too far based on PING).
            # 2. OR, Current IR is no longer strong enough (fell below consideration threshold).
            # 3. OR, Significant IR decrease (sharp edge), but only if previous point was also strong.
            #    (This avoids ending on noise if IR was already weak).
            
            # Check for sharp drop first, only if both points were strong enough to begin with
            sharp_ir_drop = (current_ir_is_strong_enough and prev_ir_is_strong_enough and ir_change <= -IR_EDGE_THRESHOLD)
            
            if not (ping_is_relevant and current_ir_is_strong_enough) or sharp_ir_drop:
                in_object_segment = False
                if len(current_segment_points) >= OBJECT_MIN_POINTS:
                    objects_segments.append(list(current_segment_points))
                current_segment_points = []
                
                # Check if the current point that ENDED this segment could START a new one
                # (e.g. ended due to sharp IR drop, but current point is still valid and strong)
                # This handles cases like two objects close together.
                if ping_is_relevant and current_ir_is_strong_enough and \
                   (ir_change >= IR_EDGE_THRESHOLD or (not prev_ir_is_strong_enough)):
                     # The prev_ir_is_strong_enough here actually refers to scan_data_padded[i-1]'s ir for THIS iteration
                     # which was the point that caused the previous segment to end *if* it was a sharp drop.
                     # More simply, if the point is valid, let the next iteration handle starting a new segment.
                     # However, if it was a sharp drop, the *current* point is the start of the "valley".
                     # For now, let the main loop handle new segment starts in the next iteration.
                     pass

            else: # Continue current segment
                current_segment_points.append((angle, dist_cm, ir_raw))

    if in_object_segment and len(current_segment_points) >= OBJECT_MIN_POINTS: # Catch any trailing segment
        objects_segments.append(list(current_segment_points))
    # --- End of IR-Based Object Segmentation ---

    # --- Process Segments into Plottable Objects (similar to before, but segments are IR-defined) ---
    plotted_objects_info = []
    for segment in objects_segments:
        if not segment: continue

        angles = [p[0] for p in segment]
        # PING distances from the IR-defined segment are used for geometry
        distances_cm = [p[1] for p in segment if (p[1] > 0 and p[1] <= OBJECT_MAX_DIST_CM)]
        
        if not distances_cm: continue # Need valid PING readings in the segment

        start_angle_obj = angles[0]
        end_angle_obj = angles[-1]
        angular_width_deg = abs(end_angle_obj - start_angle_obj)

        if angular_width_deg < OBJECT_MIN_ANGLE_WIDTH_DEG:
            continue

        closest_dist_in_segment_cm = min(distances_cm)
        
        # Estimate linear width using PING distances at the segment edges
        # Find the (dist_cm, ir_raw) for the start and end angles of the segment
        dist_at_start_angle = segment[0][1]
        dist_at_end_angle = segment[-1][1]
        
        linear_width_cm = 0
        if angular_width_deg > 0.1 and \
           (dist_at_start_angle > 0 and dist_at_start_angle <= OBJECT_MAX_DIST_CM) and \
           (dist_at_end_angle > 0 and dist_at_end_angle <= OBJECT_MAX_DIST_CM):
            angle_diff_rad = math.radians(angular_width_deg)
            term = (dist_at_start_angle**2 + dist_at_end_angle**2 -
                    2 * dist_at_start_angle * dist_at_end_angle * math.cos(angle_diff_rad))
            linear_width_cm = math.sqrt(max(0, term))
        else:
            # Fallback: Estimate width based on angular span and closest distance
            # This is a rough approximation: arc length = radius * angle_in_radians
            if closest_dist_in_segment_cm > 0 :
                 linear_width_cm = closest_dist_in_segment_cm * math.radians(angular_width_deg)
            else: # further fallback
                 linear_width_cm = 5.0


        plotted_objects_info.append({
            'middle_angle_servo': (start_angle_obj + end_angle_obj) / 2.0,
            'closest_distance_cm': closest_dist_in_segment_cm,
            'linear_width_cm': linear_width_cm
        })
    # --- End Processing Segments ---

    # print(f"Found {len(objects_segments)} IR segments, {len(plotted_objects_info)} objects after filtering.") # Optional debug

    # --- Calculate Sensor's current position on the map (same as before) ---
    sensor_offset_pixels = SENSOR_FORWARD_OFFSET_CM * MAP_SCALE
    robot_current_angle_rad = math.radians(robot_angle_deg)
    sensor_origin_x = robot_x + sensor_offset_pixels * math.cos(robot_current_angle_rad)
    sensor_origin_y = robot_y - sensor_offset_pixels * math.sin(robot_current_angle_rad)

    # --- Plotting Validated Objects (using adjusted distance, same as your last version) ---
    for obj_info in plotted_objects_info:
        if obj_info['closest_distance_cm'] <= 0: continue # Already filtered by OBJECT_MAX_DIST_CM earlier

        object_angle_relative_to_robot_forward_deg = obj_info['middle_angle_servo'] - 90.0
        world_angle_of_object_center_deg = robot_angle_deg + object_angle_relative_to_robot_forward_deg
        obj_center_angle_world_rad = math.radians(world_angle_of_object_center_deg)

        obj_closest_edge_dist_cm = obj_info['closest_distance_cm']
        obj_visual_radius_cm = obj_info['linear_width_cm'] / 2.0
        oval_center_dist_from_sensor_cm = obj_closest_edge_dist_cm + obj_visual_radius_cm
        oval_center_dist_pixels = oval_center_dist_from_sensor_cm * MAP_SCALE
        
        obj_oval_center_x = sensor_origin_x + oval_center_dist_pixels * math.cos(obj_center_angle_world_rad)
        obj_oval_center_y = sensor_origin_y - oval_center_dist_pixels * math.sin(obj_center_angle_world_rad)

        obj_visual_radius_pixels = max(obj_visual_radius_cm * MAP_SCALE, 2.0) 

        map_canvas.create_oval(obj_oval_center_x - obj_visual_radius_pixels,
                               obj_oval_center_y - obj_visual_radius_pixels,
                               obj_oval_center_x + obj_visual_radius_pixels,
                               obj_oval_center_y + obj_visual_radius_pixels,
                               outline="darkmagenta", fill="orchid", width=2, tags="detected_object") # New colors
        
        map_canvas.create_text(obj_oval_center_x, obj_oval_center_y,
                               text=f"{obj_info['closest_distance_cm']:.0f}", 
                               fill="black", font=("Arial", 7), tags="detected_object")

def update_map_with_bump(bump_info_string):
    """Draws a bump indicator on the map."""
    global robot_x, robot_y, robot_angle_deg
    print(f"Updating map with bump: {bump_info_string}")
    bump_offset_pixels = ROBOT_RADIUS_PIXELS
    bump_angle_relative_deg = 0
    if "LEFT" in bump_info_string: bump_angle_relative_deg = 45
    elif "RIGHT" in bump_info_string: bump_angle_relative_deg = -45

    bump_angle_world_deg = robot_angle_deg + bump_angle_relative_deg
    bump_angle_world_rad = math.radians(bump_angle_world_deg)
    bump_x = robot_x + bump_offset_pixels * math.cos(bump_angle_world_rad)
    bump_y = robot_y - bump_offset_pixels * math.sin(bump_angle_world_rad)
    radius = 5
    map_canvas.create_rectangle(bump_x - radius, bump_y - radius, bump_x + radius, bump_y + radius,
                                fill="red", outline="darkred", tags="bump_event")

# ---vvv--- MODIFIED FUNCTION (Added Logging) ---vvv---
def update_robot_position_and_trail(move_data_string):
    """Updates the robot's pose (x, y, angle) and draws a trail segment."""
    global robot_x, robot_y, robot_angle_deg
    print(f"--- Pose Update --- Received MOVE data: '{move_data_string}'") # Log incoming data
    try:
        dist_cm, angle_deg_delta = 0.0, 0.0
        # Parse distance and angle change from the MOVE string
        parts = move_data_string.split(',')
        for part in parts:
            key_value = part.split('=')
            if len(key_value) == 2:
                key, value = key_value[0].strip(), key_value[1].strip()
                if key == "DIST_CM":
                    dist_cm = float(value)
                elif key == "ANGLE_DEG":
                    angle_deg_delta = float(value)

        print(f"--- Pose Update --- Parsed: Dist={dist_cm:.2f} cm, Angle Delta={angle_deg_delta:.2f} deg") # Log parsed values

        # Store previous position for drawing the trail
        prev_x, prev_y = robot_x, robot_y
        prev_angle = robot_angle_deg

        # Update angle FIRST
        robot_angle_deg += angle_deg_delta
        robot_angle_deg %= 360 # Normalize angle
        if robot_angle_deg < 0: robot_angle_deg += 360

        # Calculate displacement based on the NEW angle
        dist_pixels = dist_cm * MAP_SCALE
        robot_angle_rad = math.radians(robot_angle_deg) # Use updated angle
        delta_x = dist_pixels * math.cos(robot_angle_rad)
        delta_y = -dist_pixels * math.sin(robot_angle_rad) # Y decreases upwards

        # Update robot's position
        robot_x += delta_x
        robot_y += delta_y

        print(f"--- Pose Update --- Old Pose: ({prev_x:.1f}, {prev_y:.1f}), {prev_angle:.1f} deg")
        print(f"--- Pose Update --- New Pose: ({robot_x:.1f}, {robot_y:.1f}), {robot_angle_deg:.1f} deg") # Log new pose

        # Draw trail segment if significant movement occurred
        if abs(dist_cm) > 0.1 or abs(angle_deg_delta) > 0.1:
             map_canvas.create_line(prev_x, prev_y, robot_x, robot_y, fill="darkgreen", width=2, tags="trail")

        # Redraw robot at its new position and orientation
        draw_robot_on_map()
    except ValueError as ve:
        print(f"ValueError processing move data '{move_data_string}': {ve}")
    except Exception as e:
        print(f"Error processing move data '{move_data_string}': {e}")
# ---^^^--- MODIFIED FUNCTION ---^^^---


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
    except tk.TclError:
        print("Radar canvas not ready, retrying draw...")
        app.after(50, draw_radar_plot)
        return

    if canvas_width <= 1 or canvas_height <= 1:
        print("Radar canvas too small, skipping draw.")
        return

    center_x = canvas_width / 2
    center_y = canvas_height # Base Y at the bottom
    max_radius_pixels = min(canvas_width / 2.0, canvas_height) * 0.9

    # Use the same max distance for the PING plot scale and grid
    max_dist_cm = 330.0 # Max range for PING display and grid

    # --- Draw Grid (same as before, scaled to max_dist_cm) ---
    grid_color = "#A0A0A0"; label_color = "#505050"
    # Grid arcs
    for r_cm in [50, 100, 150, 200, 250, 300]:
        r_ratio = r_cm / max_dist_cm;
        if r_ratio > 1.0: continue
        r_pixels = max_radius_pixels * r_ratio
        # Basic check for valid coordinates before drawing arcs/text
        if all(map(math.isfinite, [center_x - r_pixels, center_y - r_pixels, center_x + r_pixels, center_y + r_pixels])):
            radar_canvas.create_arc(center_x - r_pixels, center_y - r_pixels, center_x + r_pixels, center_y + r_pixels,
                                    start=0, extent=180, outline=grid_color, style=tk.ARC, tags="scan_plot_grid")
            # Place text slightly outside the arc
            text_r_pixels = r_pixels + 2
            # Check text position validity
            if math.isfinite(center_x + 5) and math.isfinite(center_y - text_r_pixels + 8):
                 radar_canvas.create_text(center_x + 5, center_y - text_r_pixels + 8, text=f"{r_cm:.0f}", fill=label_color, font=("Arial", 7), anchor="w", tags="scan_plot_grid")

    # Radial lines
    for angle_deg in range(0, 181, 30):
        plot_angle_deg = angle_deg
        angle_rad = math.radians(plot_angle_deg)
        line_end_x = center_x + max_radius_pixels * math.cos(angle_rad)
        line_end_y = center_y - max_radius_pixels * math.sin(angle_rad)
        # Check line coordinate validity
        if all(map(math.isfinite, [center_x, center_y, line_end_x, line_end_y])):
            radar_canvas.create_line(center_x, center_y, line_end_x, line_end_y, fill=grid_color, tags="scan_plot_grid")

        # Angle Labels (Add checks for label positions)
        label_rad = max_radius_pixels * 1.05
        label_x = center_x + label_rad * math.cos(angle_rad)
        label_y = center_y - label_rad * math.sin(angle_rad)
        anchor_pos = tk.CENTER; x_offset = 0; y_offset = 0
        # (Anchor logic remains the same)
        if plot_angle_deg == 0: anchor_pos = tk.W; x_offset = 3
        elif plot_angle_deg == 180: anchor_pos = tk.E; x_offset = -3
        elif plot_angle_deg == 90: anchor_pos = tk.S; y_offset = -3
        elif plot_angle_deg > 90: anchor_pos = tk.SW; y_offset = -1; x_offset = 1
        elif plot_angle_deg < 90: anchor_pos = tk.SE; y_offset = -1; x_offset = -1
        # Check label coordinate validity
        if all(map(math.isfinite, [label_x + x_offset, label_y + y_offset])):
             radar_canvas.create_text(label_x + x_offset, label_y + y_offset, text=f"{angle_deg}°", fill=label_color, font=("Arial", 8), anchor=anchor_pos, tags="scan_plot_grid")

    # --- Draw Robot Icon (same as before) ---
    robot_icon_size = 5
    if all(map(math.isfinite, [center_x - robot_icon_size, center_y - robot_icon_size, center_x + robot_icon_size, center_y])):
        radar_canvas.create_oval(center_x - robot_icon_size, center_y - robot_icon_size, center_x + robot_icon_size, center_y, fill="darkgreen", outline="black", tags="radar_robot")
        radar_canvas.create_line(center_x, center_y, center_x, center_y - robot_icon_size * 1.5, fill="white", width=1, arrow=tk.LAST, tags="radar_robot")

    # --- Prepare to Plot Scan Data ---
    ping_points_pixels = [] # Holds (x, y) for red PING line
    ir_points_pixels = []   # Holds (x, y) for blue IR line
    num_ping_plotted = 0
    num_ir_plotted = 0
    num_skipped = 0

    # --- Loop through scan data ---
    for angle_deg, dist_cm, ir_raw in last_scan_data:
        plot_angle_deg = angle_deg
        angle_rad = math.radians(plot_angle_deg)
        valid_ping_point = False
        valid_ir_point = False

        # --- Process PING Data ---
        if dist_cm > 0 and dist_cm <= max_dist_cm:
            # Scale distance relative to the max_dist_cm for PING plot
            ping_plot_radius_pixels = min(dist_cm / max_dist_cm, 1.0) * max_radius_pixels
            ping_point_x = center_x + ping_plot_radius_pixels * math.cos(angle_rad)
            ping_point_y = center_y - ping_plot_radius_pixels * math.sin(angle_rad)

            if math.isfinite(ping_point_x) and math.isfinite(ping_point_y):
                ping_points_pixels.extend([ping_point_x, ping_point_y])
                valid_ping_point = True
                num_ping_plotted += 1
            else:
                print(f"Invalid PING coordinate: angle={angle_deg}, dist={dist_cm}")
        else:
            # Invalid PING distance, break the PING line segment
            pass

        # If current PING point is invalid, draw previous segment if long enough
        if not valid_ping_point and len(ping_points_pixels) >= 4:
            try:
                radar_canvas.create_line(ping_points_pixels, fill="red", width=2, tags="ping_scan_plot")
            except Exception as e:
                print(f"Error drawing PING line segment (invalid point): {e}")
            ping_points_pixels = [] # Reset for next segment

        # --- Process IR Data ---
        if ir_raw >= IR_VALID_MIN: # Only plot if IR value is reasonably high
            # Clamp the raw value to the expected range for normalization
            clamped_ir = max(IR_MIN_RAW, min(ir_raw, IR_MAX_RAW))
            # Normalize: higher value -> closer to 0; lower value -> closer to 1
            norm_ir = (clamped_ir - IR_MIN_RAW) / (IR_MAX_RAW - IR_MIN_RAW)
            # Invert for plotting: closer (high IR, norm_ir near 1) -> smaller radius
            ir_plot_radius_pixels = (1.0 - norm_ir) * max_radius_pixels

            ir_point_x = center_x + ir_plot_radius_pixels * math.cos(angle_rad)
            ir_point_y = center_y - ir_plot_radius_pixels * math.sin(angle_rad)

            if math.isfinite(ir_point_x) and math.isfinite(ir_point_y):
                ir_points_pixels.extend([ir_point_x, ir_point_y])
                valid_ir_point = True
                num_ir_plotted += 1
            else:
                 print(f"Invalid IR coordinate: angle={angle_deg}, ir_raw={ir_raw}")
        else:
            # Invalid or too low IR value, break the IR line segment
            num_skipped += 1
            pass

        # If current IR point is invalid, draw previous segment if long enough
        if not valid_ir_point and len(ir_points_pixels) >= 4:
            try:
                radar_canvas.create_line(ir_points_pixels, fill="blue", width=2, tags="ir_scan_plot")
            except Exception as e:
                print(f"Error drawing IR line segment (invalid point): {e}")
            ir_points_pixels = [] # Reset for next segment


    # --- Draw the final segments after the loop ---
    if len(ping_points_pixels) >= 4:
        try:
            radar_canvas.create_line(ping_points_pixels, fill="red", width=2, tags="ping_scan_plot")
        except Exception as e:
            print(f"Error drawing final PING line segment: {e}")

    if len(ir_points_pixels) >= 4:
        try:
            radar_canvas.create_line(ir_points_pixels, fill="blue", width=2, tags="ir_scan_plot")
        except Exception as e:
            print(f"Error drawing final IR line segment: {e}")

    # print(f"Radar Draw Complete. PING Plotted: {num_ping_plotted}, IR Plotted: {num_ir_plotted}, IR Skipped: {num_skipped}") # Optional


# (clear_map_features, draw_robot_on_map functions remain the same)
def clear_map_features(tag_to_clear):
    """Clears specific features (trail, objects, bumps) from the map."""
    map_canvas.delete(tag_to_clear)
    if tag_to_clear == "trail":
        initialize_robot_position()

def draw_robot_on_map(event=None):
    """Draws the robot icon (circle) on the map canvas at its current pose."""
    global robot_x, robot_y, robot_angle_deg, map_canvas, MAP_SCALE # Add map_canvas and MAP_SCALE if needed in scope
    map_canvas.delete("robot") # Keep this to clear the old drawing

    # Use is_connected or check if robot coordinates are valid before drawing
    if not is_connected and not (robot_x > 0 and robot_y > 0): return

    # Calculate radius in pixels
    ROBOT_REAL_RADIUS_CM = 33.0
    radius_pixels = ROBOT_REAL_RADIUS_CM * MAP_SCALE

    # Center coordinates
    cx, cy = robot_x, robot_y

    # Calculate bounding box for the circle
    x1 = cx - radius_pixels
    y1 = cy - radius_pixels
    x2 = cx + radius_pixels
    y2 = cy + radius_pixels

    # Check if coordinates are valid before drawing
    if all(map(math.isfinite, [x1, y1, x2, y2])):
        # Draw the circle
        map_canvas.create_oval(x1, y1, x2, y2,
                                  fill="darkblue", outline="black", width=1, tags="robot") # Changed fill color

        # Draw a line to indicate orientation
        angle_rad = math.radians(robot_angle_deg)
        line_end_x = cx + radius_pixels * math.cos(angle_rad)
        line_end_y = cy - radius_pixels * math.sin(angle_rad) # Y decreases upwards

        if all(map(math.isfinite, [line_end_x, line_end_y])):
             map_canvas.create_line(cx, cy, line_end_x, line_end_y,
                                     fill="white", width=2, tags="robot")
    else:
        print(f"Warning: Invalid coordinates for robot drawing at ({cx}, {cy}), angle {robot_angle_deg}")


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
radar_canvas.bind("<Configure>", lambda e: draw_radar_plot()) # Redraw radar on resize
clear_radar_button = ttk.Button(radar_frame, text="Clear Radar", command=lambda: radar_canvas.delete("ping_scan_plot", "ir_scan_plot")); clear_radar_button.pack(side=tk.BOTTOM, pady=2)


# --- Right Pane ---
map_frame = ttk.LabelFrame(paned_window, text="Test Field Map (Top-Down View)"); paned_window.add(map_frame, weight=3) # Give it more weight
map_canvas = tk.Canvas(map_frame, bg="lightgrey", highlightthickness=1, highlightbackground="grey"); map_canvas.pack(expand=True, fill="both")
map_canvas.bind("<Configure>", draw_robot_on_map) # Redraw robot if canvas size changes
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
        app.after(200, app.destroy)

app.protocol("WM_DELETE_WINDOW", on_closing)
unbind_keys()

try:
    update_sensor_status("BUMP_L=0,BUMP_R=0,CLIFF_L_SIG=0,CLIFF_FL_SIG=0,CLIFF_FR_SIG=0,CLIFF_R_SIG=0,PING=0.0")
    draw_radar_plot()
except Exception as e:
    print(f"ERROR during initial GUI update: {e}")
    messagebox.showerror("Startup Error", f"An error occurred during initial GUI setup:\n{e}")

app.mainloop()

# --- Cleanup ---
print("Application closing.")
stop_thread_flag.set()