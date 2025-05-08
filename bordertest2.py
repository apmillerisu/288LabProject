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
# CLIFF_LINE_LENGTH_PIXELS REMOVED

# --- Global Variables ---
cybot_socket = None
is_connected = False
message_queue = queue.Queue()
stop_thread_flag = threading.Event()

# Robot Pose (Position and Orientation) - Initialized when map is ready
robot_x = 0.0 # This will be set by initialize_robot_position for the map icon
robot_y = 0.0 # This will be set by initialize_robot_position for the map icon
robot_angle_deg = 90.0 # Global angle used for map icon orientation (now static)

# Scan Data Storage
current_scan_buffer = [] # Temp buffer while scan is in progress
last_scan_data = [] # Stores the points (angle_deg, dist_cm, ir_raw) of the last completed scan

# ---vvv--- NEW Global Variables for Movement Trail ---vvv---
movement_history = []  # Stores dicts of {'type': 'move'/'turn', 'distance': float, 'angle': float}
trail_canvas = None    # Will hold the new canvas widget for the trail
TRAIL_SCALE = 1.5      # Pixels per cm for the trail display (adjust as needed)
DEBUG_TRAIL_PANEL = False # Set to True by user if trail debugging needed
# REMOVED: last_cliff_pattern, last_cliff_type
# ---^^^--- NEW Global Variables for Movement Trail ---^^^---


# --- Network Communication ---
def connect_to_cybot():
    """Establishes a socket connection to the CyBot."""
    global cybot_socket, is_connected, robot_x, robot_y, robot_angle_deg
    if is_connected:
        status_label.config(text="Already connected.", foreground="orange")
        return

    robot_angle_deg = 90.0 # Reset orientation for map icon

    try:
        status_label.config(text=f"Connecting to {CYBOT_IP}:{CYBOT_PORT}...", foreground="black")
        app.update_idletasks()

        cybot_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        cybot_socket.settimeout(5.0)
        cybot_socket.connect((CYBOT_IP, CYBOT_PORT))
        cybot_socket.settimeout(None)
        is_connected = True
        status_label.config(text="Connected to CyBot!", foreground="green")

        connect_button.config(state=tk.DISABLED)
        disconnect_button.config(state=tk.NORMAL)
        scan_button.config(state=tk.NORMAL)
        jingle_button.config(state=tk.NORMAL)

        bind_keys()
        app.after(100, initialize_robot_position) # Set map icon to center
        app.after(150, initialize_trail_display)
        app.after(200, redraw_trail_on_panel)

        stop_thread_flag.clear()
        listen_thread = threading.Thread(target=listen_for_messages, daemon=True)
        listen_thread.start()
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
    stop_thread_flag.set()
    if cybot_socket:
        try:
            cybot_socket.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            cybot_socket.close()
        except Exception:
            pass
        finally:
            cybot_socket = None
    is_connected = False
    status_label.config(text="Disconnected.", foreground="red")
    connect_button.config(state=tk.NORMAL)
    disconnect_button.config(state=tk.DISABLED)
    scan_button.config(state=tk.DISABLED)
    jingle_button.config(state=tk.DISABLED)
    unbind_keys()
    print("Disconnected.")

def send_command(command_to_send):
    if not is_connected or not cybot_socket:
        print("Warning: Cannot send command, not connected.")
        return
    if not command_to_send:
        print("Warning: Command cannot be empty.")
        return
    try:
        if not command_to_send.endswith('\n'):
            command_to_send += '\n'
        cybot_socket.sendall(command_to_send.encode('utf-8'))
        raw_data_text.insert(tk.END, f"--> Sent: {command_to_send}")
        raw_data_text.see(tk.END)
    except Exception as e:
        status_label.config(text=f"Send failed: {e}", foreground="red")
        messagebox.showerror("Send Error", f"Failed to send command.\nError: {e}")
        app.after(0, disconnect_from_cybot)

# --- Key Binding Functions ---
def handle_keypress(event):
    if app.focus_get() != raw_data_text:
        key = event.keysym.lower()
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
def listen_for_messages():
    global cybot_socket, is_connected
    print("Listening thread started.")
    buffer = ""
    while not stop_thread_flag.is_set():
        try:
            cybot_socket.settimeout(0.2)
            data_bytes = cybot_socket.recv(1024)
            cybot_socket.settimeout(None)
            if data_bytes:
                message_part = data_bytes.decode('utf-8', errors='replace')
                buffer += message_part
                while '\n' in buffer:
                    message, buffer = buffer.split('\n', 1)
                    message_queue.put(message + '\n')
            else:
                print("Connection closed by server (received empty data).")
                if not stop_thread_flag.is_set():
                    message_queue.put("CONNECTION_CLOSED\n")
                break
        except socket.timeout:
            continue
        except socket.error as e:
            if not stop_thread_flag.is_set():
                print(f"Socket error in listening thread: {e}")
                message_queue.put("CONNECTION_ERROR\n")
            break
        except Exception as e:
            if not stop_thread_flag.is_set():
                 print(f"Unexpected error in listening thread: {e}")
                 message_queue.put("CONNECTION_ERROR\n")
            break
    print("Listening thread finished.")
    if not stop_thread_flag.is_set() and is_connected:
        app.after(0, disconnect_from_cybot)

def process_incoming_messages():
    global is_connected, stop_thread_flag
    try:
        while not message_queue.empty():
            message = message_queue.get_nowait()
            if message == "CONNECTION_CLOSED\n":
                 if is_connected:
                     messagebox.showinfo("Connection Info", "Connection closed by CyBot.")
                     disconnect_from_cybot()
                 break
            elif message == "CONNECTION_ERROR\n":
                 if is_connected:
                     messagebox.showerror("Connection Error", "Socket error occurred.")
                     disconnect_from_cybot()
                 break
            else:
                timestamp = time.strftime("%H:%M:%S", time.localtime())
                message_content = message.strip()
                log_this_message = not message_content.startswith("STATUS:")
                if log_this_message:
                    raw_data_text.insert(tk.END, f"[{timestamp}] {message}")
                    raw_data_text.see(tk.END)
                parse_cybot_message(message)
    except queue.Empty:
        pass
    except Exception as e:
        print(f"ERROR processing message in GUI: {e}")
    if is_connected or not stop_thread_flag.is_set():
         app.after(100, process_incoming_messages)

def parse_cybot_message(message):
    global current_scan_buffer, last_scan_data
    line = message.strip()
    if not line: return
    try:
        if "END SCAN" in line.upper() and line.startswith("SCAN:"):
            if DEBUG_OBJECT_DETECTION: print(f"\nScan END marker received: '{line}'")
            if DEBUG_OBJECT_DETECTION: print(f"Buffer size BEFORE processing END: {len(current_scan_buffer)}")
            if current_scan_buffer:
                last_scan_data = current_scan_buffer[:]
                current_scan_buffer = []
                if DEBUG_OBJECT_DETECTION: print(f"Copied data to last_scan_data (size: {len(last_scan_data)}). Cleared buffer.")
                app.after(10, draw_radar_plot)
                app.after(20, detect_and_plot_objects)
            else:
                if DEBUG_OBJECT_DETECTION: print("Scan END received, but current_scan_buffer is empty. No plotting.")
            return
        elif line.startswith("STATUS:"):
            update_sensor_status(line[len("STATUS:"):]) # Simplified, only updates sensor display
        elif line.startswith("SCAN:"):
             append_scan_data(line[len("SCAN:"):], is_mock_data=False)
        elif line.startswith("MOVE:"):
             update_robot_position_and_trail(line[len("MOVE:"):]) # Only updates trail panel history/drawing
        elif line.startswith("BUMP_EVENT:"):
             update_map_with_bump(line[len("BUMP_EVENT:"):]) # Plots bumps relative to static map icon
        elif line.startswith("INFO:") or line.startswith("DEBUG:") or line.startswith("ERROR:") or line.startswith("ACK:"):
             pass
    except Exception as e:
        print(f"Error parsing line '{line}': {e}")

# --- GUI Update Functions ---
def initialize_robot_position():
    """Sets the robot's initial (x,y) position to the center of the map canvas for the icon."""
    global robot_x, robot_y, map_canvas
    if not map_canvas: return
    map_canvas.update_idletasks()
    map_width = map_canvas.winfo_width()
    map_height = map_canvas.winfo_height()
    if map_width > 1 and map_height > 1:
        robot_x = map_width / 2
        robot_y = map_height / 2
        global robot_angle_deg
        robot_angle_deg = 90.0 # Keep icon pointing North
        print(f"Robot icon initialized at map center: ({robot_x:.1f}, {robot_y:.1f})")
        draw_robot_on_map()
    else:
        print("Map canvas not ready for robot icon initialization, retrying...")
        app.after(100, initialize_robot_position)

def update_sensor_status(status_string):
    """Parses STATUS and updates sensor display ONLY."""
    # No longer updates global cliff state variables

    sensor_canvas.delete("status_indicator")
    left_bumper_color, right_bumper_color = "grey", "grey"
    cliff_l_sig_val_str, cliff_fl_sig_val_str, cliff_fr_sig_val_str, cliff_r_sig_val_str = "N/A", "N/A", "N/A", "N/A"
    cliff_l_color, cliff_fl_color, cliff_fr_color, cliff_r_color = "grey", "grey", "grey", "grey"
    ping_val = "N/A"
    heading_val_str = "N/A"

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
                elif key == "Heading":
                    heading_val_str = value_str
    except Exception as e:
        print(f"Error parsing status string '{status_string}': {e}")
        cliff_l_sig_val_str, cliff_fl_sig_val_str, cliff_fr_sig_val_str, cliff_r_sig_val_str = "Err", "Err", "Err", "Err"
        ping_val = "Err"; heading_val_str = "Err"
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
    ping_label.config(text=f"Ping: {ping_val} cm Heading: {heading_val_str} degrees")


def append_scan_data(scan_data_string, is_mock_data=False):
    global current_scan_buffer
    try:
        angle_deg, dist_cm, ir_raw = None, None, None
        if is_mock_data:
             parts = scan_data_string.split()
             if len(parts) >= 2:
                 angle_deg = float(parts[0])
                 dist_m = float(parts[1])
                 dist_cm = dist_m * 100.0
                 ir_raw = 0
        else:
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
    except ValueError as ve:
        print(f"ValueError converting scan data '{scan_data_string}': {ve}")
    except Exception as e:
        print(f"Error appending scan data '{scan_data_string}': {e}")

def update_map_with_scan(scan_data_string):
    pass

def detect_and_plot_objects(scan_data=None):
    global robot_x, robot_y, robot_angle_deg, last_scan_data, map_canvas
    global MAP_SCALE, SENSOR_FORWARD_OFFSET_CM, OBJECT_MAX_DIST_CM
    global OBJECT_MIN_POINTS, OBJECT_MIN_ANGLE_WIDTH_DEG
    global IR_MIN_STRENGTH_FOR_CONSIDERATION, IR_EDGE_THRESHOLD_RISE, IR_EDGE_THRESHOLD_DROP, DEBUG_OBJECT_DETECTION
    if scan_data is None: scan_data = last_scan_data
    if not map_canvas: return
    map_canvas.delete("detected_object")
    if not scan_data:
        if DEBUG_OBJECT_DETECTION: print("detect_and_plot_objects: No scan data to process.")
        return
    scan_data_sorted = sorted(scan_data, key=lambda p: p[0])
    objects_segments = []
    current_segment_points = []
    in_object_segment = False
    dummy_ir_weak = min(IR_MIN_STRENGTH_FOR_CONSIDERATION / 2, 50)
    if DEBUG_OBJECT_DETECTION: print(f"\n--- Starting Object Detection Cycle ({len(scan_data_sorted)} points) ---")
    if DEBUG_OBJECT_DETECTION:
        print(f"Params: IR_MIN_CONSIDER={IR_MIN_STRENGTH_FOR_CONSIDERATION}, IR_RISE_THRESH={IR_EDGE_THRESHOLD_RISE}, IR_DROP_THRESH={IR_EDGE_THRESHOLD_DROP}")
    prev_ir_raw_val = dummy_ir_weak
    for i in range(len(scan_data_sorted)):
        angle, dist_cm, ir_raw = scan_data_sorted[i]
        if i > 0:
            prev_ir_raw_val = scan_data_sorted[i-1][2]
        ir_change = ir_raw - prev_ir_raw_val
        ping_is_relevant = (dist_cm > 0 and dist_cm <= OBJECT_MAX_DIST_CM)
        current_ir_is_strong = (ir_raw >= IR_MIN_STRENGTH_FOR_CONSIDERATION)
        prev_ir_was_strong = (prev_ir_raw_val >= IR_MIN_STRENGTH_FOR_CONSIDERATION)
        if DEBUG_OBJECT_DETECTION and i < 5:
             print(f"  Point {i}: Angle={angle:.1f}, Dist={dist_cm:.1f}, IR={ir_raw} (PrevIR={prev_ir_raw_val}, Change={ir_change})")
             print(f"     RelevantPING={ping_is_relevant}, CurrStrongIR={current_ir_is_strong}, PrevStrongIR={prev_ir_was_strong}")
        if not in_object_segment:
            if ping_is_relevant and current_ir_is_strong:
                is_sharp_rise = (ir_change >= IR_EDGE_THRESHOLD_RISE)
                is_transition_to_strong = (not prev_ir_was_strong)
                if is_sharp_rise or is_transition_to_strong:
                    in_object_segment = True
                    current_segment_points = [(angle, dist_cm, ir_raw)]
                    if DEBUG_OBJECT_DETECTION:
                        print(f"  Segment START: Angle={angle:.1f}, IR={ir_raw}, Dist={dist_cm:.1f}. Rise={is_sharp_rise}, Trans={is_transition_to_strong}. Change={ir_change}")
        else:
            point_is_unsuitable = not (ping_is_relevant and current_ir_is_strong)
            is_sharp_drop = (current_ir_is_strong and prev_ir_was_strong and (-ir_change >= IR_EDGE_THRESHOLD_DROP) )
            if point_is_unsuitable or is_sharp_drop:
                in_object_segment = False
                if len(current_segment_points) >= OBJECT_MIN_POINTS:
                    objects_segments.append(list(current_segment_points))
                    if DEBUG_OBJECT_DETECTION:
                        print(f"  Segment ENDED before Angle={angle:.1f}. Reason: Unsuitable={point_is_unsuitable}, SharpDrop={is_sharp_drop}. PrevIR={prev_ir_raw_val}, CurrIR={ir_raw}")
                        print(f"    Stored segment with {len(current_segment_points)} points. Last point: {current_segment_points[-1][0]:.1f} deg.")
                current_segment_points = []
                if ping_is_relevant and current_ir_is_strong:
                    is_sharp_rise = (ir_change >= IR_EDGE_THRESHOLD_RISE)
                    is_transition_to_strong = (not prev_ir_was_strong) and current_ir_is_strong
                    if is_sharp_rise or is_transition_to_strong:
                        in_object_segment = True
                        current_segment_points = [(angle, dist_cm, ir_raw)]
                        if DEBUG_OBJECT_DETECTION:
                            print(f"  Segment RE-START immediately at Angle={angle:.1f}, IR={ir_raw}. Rise={is_sharp_rise}, Trans={is_transition_to_strong}")
            else:
                current_segment_points.append((angle, dist_cm, ir_raw))
    if in_object_segment and len(current_segment_points) >= OBJECT_MIN_POINTS:
        objects_segments.append(list(current_segment_points))
        if DEBUG_OBJECT_DETECTION: print(f"  Trailing segment stored with {len(current_segment_points)} points. Last point: {current_segment_points[-1][0]:.1f} deg.")
    if DEBUG_OBJECT_DETECTION: print(f"--- Object Detection Cycle END. Found {len(objects_segments)} raw segments. ---")
    plotted_objects_info = []
    for idx, segment in enumerate(objects_segments):
        if not segment: continue
        angles = [p[0] for p in segment]
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
        dist_at_start_angle = segment[0][1]
        dist_at_end_angle = segment[-1][1]
        if not (dist_at_start_angle > 0 and dist_at_start_angle <= OBJECT_MAX_DIST_CM and \
                dist_at_end_angle > 0 and dist_at_end_angle <= OBJECT_MAX_DIST_CM):
            if DEBUG_OBJECT_DETECTION: print(f"  Segment {idx} skipped: Invalid edge PING distances for width calc (Start: {dist_at_start_angle:.1f}, End: {dist_at_end_angle:.1f}).")
            continue
        linear_width_cm = 0
        angle_diff_rad = math.radians(angular_width_deg)
        term_for_sqrt = (dist_at_start_angle**2 + dist_at_end_angle**2 -
                         2 * dist_at_start_angle * dist_at_end_angle * math.cos(angle_diff_rad))
        if term_for_sqrt >= 0:
            linear_width_cm = math.sqrt(term_for_sqrt)
        else:
            if DEBUG_OBJECT_DETECTION: print(f"  Segment {idx} Warning: Negative term for sqrt in width calc ({term_for_sqrt:.2f}). Using fallback.")
            avg_dist_cm = sum(distances_cm) / len(distances_cm)
            linear_width_cm = avg_dist_cm * angle_diff_rad
        closest_dist_in_segment_cm = min(distances_cm)
        plotted_objects_info.append({
            'middle_angle_servo': (start_angle_obj + end_angle_obj) / 2.0,
            'closest_distance_cm': closest_dist_in_segment_cm,
            'linear_width_cm': linear_width_cm,
            'start_angle': start_angle_obj,
            'end_angle': end_angle_obj,
            'num_points': len(segment)
        })
        if DEBUG_OBJECT_DETECTION:
             print(f"  Plotted Object from Segment {idx}: StartAng={start_angle_obj:.1f}, EndAng={end_angle_obj:.1f}, Width={linear_width_cm:.2f}cm, ClosestDist={closest_dist_in_segment_cm:.1f}cm")
    if DEBUG_OBJECT_DETECTION: print(f"--- Found {len(plotted_objects_info)} objects after filtering. ---")
    sensor_offset_pixels = SENSOR_FORWARD_OFFSET_CM * MAP_SCALE
    robot_current_angle_rad = math.radians(robot_angle_deg) # Use static angle
    sensor_origin_x = robot_x + sensor_offset_pixels * math.cos(robot_current_angle_rad)
    sensor_origin_y = robot_y - sensor_offset_pixels * math.sin(robot_current_angle_rad)
    for obj_info in plotted_objects_info:
        if obj_info['closest_distance_cm'] <= 0 or obj_info['linear_width_cm'] <= 0: continue
        object_angle_relative_to_robot_forward_deg = obj_info['middle_angle_servo'] - 90.0
        world_angle_of_object_center_deg = robot_angle_deg + object_angle_relative_to_robot_forward_deg # Use static angle
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
                               outline="darkmagenta", fill="orchid", width=2, tags="detected_object")
        map_canvas.create_text(obj_oval_center_x, obj_oval_center_y,
                               text=f"{obj_info['closest_distance_cm']:.0f}",
                               fill="black", font=("Arial", 7), tags="detected_object")

def update_map_with_bump(bump_info_string):
    global robot_x, robot_y, robot_angle_deg, map_canvas
    if not map_canvas: return
    if DEBUG_OBJECT_DETECTION: print(f"Updating map with bump: {bump_info_string}")
    bump_angle_relative_deg = 0
    if "LEFT" in bump_info_string.upper(): bump_angle_relative_deg = 45
    elif "RIGHT" in bump_info_string.upper(): bump_angle_relative_deg = -45
    bump_angle_world_deg = robot_angle_deg + bump_angle_relative_deg # Use static angle
    bump_angle_world_rad = math.radians(bump_angle_world_deg)
    bump_indicator_offset_x = ROBOT_RADIUS_PIXELS * math.cos(bump_angle_world_rad)
    bump_indicator_offset_y = -ROBOT_RADIUS_PIXELS * math.sin(bump_angle_world_rad)
    bump_x = robot_x + bump_indicator_offset_x
    bump_y = robot_y + bump_indicator_offset_y
    radius = 5
    map_canvas.create_rectangle(bump_x - radius, bump_y - radius, bump_x + radius, bump_y + radius,
                                fill="red", outline="darkred", tags="bump_event")

# ---vvv--- MODIFIED FUNCTION: Robot icon on map is static (x,y) AND orientation ---vvv---
def update_robot_position_and_trail(move_data_string):
    """
    Processes movement data from CyBot.
    Populates movement_history for the trail panel.
    The robot's (x,y) position AND angle on the main map ARE NOT UPDATED by this function.
    The trail on the main map IS NOT DRAWN by this function.
    """
    global movement_history

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

        if DEBUG_TRAIL_PANEL:
            print(f"TRAIL_DEBUG: update_robot_pos_and_trail received: dist_cm={dist_cm}, angle_delta={angle_deg_delta}")

        # --- Add to movement history for the new trail panel ---
        if abs(angle_deg_delta) > 0.01:
            movement_history.append({'type': 'turn', 'angle': angle_deg_delta})
            if DEBUG_TRAIL_PANEL: print(f"TRAIL_DEBUG: Appending turn: {angle_deg_delta}")

        if abs(dist_cm) > 0.01:
            movement_history.append({'type': 'move', 'distance': dist_cm})
            if DEBUG_TRAIL_PANEL: print(f"TRAIL_DEBUG: Appending move: {dist_cm}")

        # After any movement, redraw the trail panel
        if abs(dist_cm) > 0.01 or abs(angle_deg_delta) > 0.01:
            if DEBUG_TRAIL_PANEL: print("TRAIL_DEBUG: Scheduling redraw_trail_on_panel")
            app.after(10, redraw_trail_on_panel)

    except ValueError as ve:
        print(f"ValueError processing move data '{move_data_string}': {ve}")
    except Exception as e:
        print(f"Error processing move data '{move_data_string}': {e}")
# ---^^^--- MODIFIED FUNCTION ---^^^---

def draw_radar_plot():
    global last_scan_data, radar_canvas
    if not radar_canvas: return
    radar_canvas.delete("all")
    if not last_scan_data: return
    try:
        canvas_width = radar_canvas.winfo_width()
        canvas_height = radar_canvas.winfo_height()
    except tk.TclError:
        app.after(50, draw_radar_plot)
        return
    if canvas_width <= 1 or canvas_height <= 1: return
    center_x = canvas_width / 2
    center_y = canvas_height
    max_radius_pixels = min(canvas_width / 2.0, canvas_height) * 0.9
    max_dist_cm_for_plot = 330.0
    grid_color = "#A0A0A0"; label_color = "#505050"
    for r_cm in [50, 100, 150, 200, 250, 300]:
        if r_cm > max_dist_cm_for_plot : continue
        r_ratio = r_cm / max_dist_cm_for_plot
        r_pixels = max_radius_pixels * r_ratio
        if all(map(math.isfinite, [center_x - r_pixels, center_y - r_pixels, center_x + r_pixels, center_y + r_pixels])):
            radar_canvas.create_arc(center_x - r_pixels, center_y - r_pixels, center_x + r_pixels, center_y + r_pixels,
                                    start=0, extent=180, outline=grid_color, style=tk.ARC, tags="scan_plot_grid")
            text_r_pixels = r_pixels + 2
            if math.isfinite(center_x + 5) and math.isfinite(center_y - text_r_pixels + 8):
                 radar_canvas.create_text(center_x + 5, center_y - text_r_pixels + 8, text=f"{r_cm:.0f}", fill=label_color, font=("Arial", 7), anchor="w", tags="scan_plot_grid")
    for angle_deg_servo_frame in range(0, 181, 30):
        plot_angle_rad = math.radians(angle_deg_servo_frame)
        line_end_x = center_x + max_radius_pixels * math.cos(plot_angle_rad)
        line_end_y = center_y - max_radius_pixels * math.sin(plot_angle_rad)
        if all(map(math.isfinite, [center_x, center_y, line_end_x, line_end_y])):
            radar_canvas.create_line(center_x, center_y, line_end_x, line_end_y, fill=grid_color, tags="scan_plot_grid")
        label_rad_offset = max_radius_pixels * 1.05
        label_x = center_x + label_rad_offset * math.cos(plot_angle_rad)
        label_y = center_y - label_rad_offset * math.sin(plot_angle_rad)
        anchor_pos = tk.CENTER; x_offset = 0; y_offset = 0
        if angle_deg_servo_frame == 0: anchor_pos = tk.W; x_offset = 3
        elif angle_deg_servo_frame == 180: anchor_pos = tk.E; x_offset = -3
        elif angle_deg_servo_frame == 90: anchor_pos = tk.S; y_offset = -3
        elif angle_deg_servo_frame > 90:
            anchor_pos = tk.NE if angle_deg_servo_frame < 135 else tk.E ; y_offset = 1; x_offset = -1
        elif angle_deg_servo_frame < 90:
            anchor_pos = tk.NW if angle_deg_servo_frame > 45 else tk.W; y_offset = 1; x_offset = 1
        if all(map(math.isfinite, [label_x + x_offset, label_y + y_offset])):
             radar_canvas.create_text(label_x + x_offset, label_y + y_offset, text=f"{angle_deg_servo_frame}°", fill=label_color, font=("Arial", 8), anchor=anchor_pos, tags="scan_plot_grid")
    robot_icon_size = 5
    if all(map(math.isfinite, [center_x - robot_icon_size, center_y - robot_icon_size, center_x + robot_icon_size, center_y])):
        radar_canvas.create_oval(center_x - robot_icon_size, center_y - robot_icon_size,
                                 center_x + robot_icon_size, center_y,
                                 fill="darkgreen", outline="black", tags="radar_robot")
        radar_canvas.create_line(center_x, center_y, center_x, center_y - robot_icon_size * 1.5,
                                 fill="white", width=1, arrow=tk.LAST, tags="radar_robot")
    ping_points_pixels = []
    ir_points_pixels = []
    for angle_deg_servo_frame, dist_cm, ir_raw in last_scan_data:
        plot_angle_rad = math.radians(angle_deg_servo_frame)
        valid_ping_point_for_current_segment = False
        valid_ir_point_for_current_segment = False
        if dist_cm > 0 and dist_cm <= max_dist_cm_for_plot:
            ping_plot_radius_pixels = (dist_cm / max_dist_cm_for_plot) * max_radius_pixels
            ping_point_x = center_x + ping_plot_radius_pixels * math.cos(plot_angle_rad)
            ping_point_y = center_y - ping_plot_radius_pixels * math.sin(plot_angle_rad)
            if math.isfinite(ping_point_x) and math.isfinite(ping_point_y):
                ping_points_pixels.extend([ping_point_x, ping_point_y])
                valid_ping_point_for_current_segment = True
        if not valid_ping_point_for_current_segment and len(ping_points_pixels) >= 4:
            try: radar_canvas.create_line(ping_points_pixels, fill="red", width=2, tags="ping_scan_plot")
            except Exception as e: print(f"Error drawing PING line segment (invalid point): {e}")
            ping_points_pixels = []
        if ir_raw >= IR_VALID_MIN:
            clamped_ir = max(IR_MIN_RAW, min(ir_raw, IR_MAX_RAW))
            norm_ir = (clamped_ir - IR_MIN_RAW) / (IR_MAX_RAW - IR_MIN_RAW)
            ir_plot_radius_pixels = (1.0 - norm_ir) * max_radius_pixels
            ir_plot_radius_pixels = max(0, ir_plot_radius_pixels)
            ir_point_x = center_x + ir_plot_radius_pixels * math.cos(plot_angle_rad)
            ir_point_y = center_y - ir_plot_radius_pixels * math.sin(plot_angle_rad)
            if math.isfinite(ir_point_x) and math.isfinite(ir_point_y):
                ir_points_pixels.extend([ir_point_x, ir_point_y])
                valid_ir_point_for_current_segment = True
        if not valid_ir_point_for_current_segment and len(ir_points_pixels) >= 4:
            try: radar_canvas.create_line(ir_points_pixels, fill="blue", width=2, tags="ir_scan_plot")
            except Exception as e: print(f"Error drawing IR line segment (invalid point): {e}")
            ir_points_pixels = []
    if len(ping_points_pixels) >= 4:
        try: radar_canvas.create_line(ping_points_pixels, fill="red", width=2, tags="ping_scan_plot")
        except Exception as e: print(f"Error drawing final PING line segment: {e}")
    if len(ir_points_pixels) >= 4:
        try: radar_canvas.create_line(ir_points_pixels, fill="blue", width=2, tags="ir_scan_plot")
        except Exception as e: print(f"Error drawing final IR line segment: {e}")

def clear_map_features(tag_to_clear):
    global map_canvas
    if not map_canvas: return
    map_canvas.delete(tag_to_clear)

def draw_robot_on_map(event=None):
    global robot_x, robot_y, robot_angle_deg, map_canvas, MAP_SCALE
    if not map_canvas: return
    map_canvas.delete("robot")
    map_canvas.update_idletasks()
    map_width = map_canvas.winfo_width()
    map_height = map_canvas.winfo_height()
    if map_width <=1 or map_height <=1: return

    cx, cy = robot_x, robot_y # Uses the static robot_x, robot_y
    radius_pixels = ROBOT_REAL_RADIUS_CM * MAP_SCALE
    x1 = cx - radius_pixels
    y1 = cy - radius_pixels
    x2 = cx + radius_pixels
    y2 = cy + radius_pixels
    if all(map(math.isfinite, [x1, y1, x2, y2])):
        map_canvas.create_oval(x1, y1, x2, y2,
                                  fill="darkblue", outline="black", width=1, tags="robot")
        # Use the static robot_angle_deg (should be 90)
        angle_rad = math.radians(robot_angle_deg)
        line_end_x = cx + radius_pixels * math.cos(angle_rad)
        line_end_y = cy - radius_pixels * math.sin(angle_rad)
        if all(map(math.isfinite, [line_end_x, line_end_y])):
             map_canvas.create_line(cx, cy, line_end_x, line_end_y,
                                     fill="white", width=2, tags="robot")

# ---vvv--- NEW/MODIFIED Trail Panel Functions ---vvv---
def initialize_trail_display():
    """Clears the movement history and redraws the trail panel."""
    global movement_history, trail_canvas
    # REMOVED: last_cliff_pattern, last_cliff_type reset
    if DEBUG_TRAIL_PANEL: print("TRAIL_DEBUG: initialize_trail_display called")
    movement_history = []
    if trail_canvas:
        trail_canvas.delete("all") # Clear everything including manual objects and start dot
        try:
            trail_canvas.update_idletasks()
            trail_canvas_width = trail_canvas.winfo_width()
            trail_canvas_height = trail_canvas.winfo_height()
            if trail_canvas_width > 1 and trail_canvas_height > 1:
                start_x = trail_canvas_width / 2
                start_y = trail_canvas_height / 2
                # Redraw start dot on initialize/clear
                trail_canvas.create_oval(start_x - 3, start_y - 3, start_x + 3, start_y + 3, fill="blue", outline="blue", tags="trail_start_dot")
        except tk.TclError as e:
            if DEBUG_TRAIL_PANEL: print(f"TRAIL_DEBUG: TclError on trail canvas access during init: {e}")
            pass

def clear_all_trails():
    """Clears movement trail panel, manual objects and recenters robot icon on the main map."""
    global map_canvas, trail_canvas
    if DEBUG_TRAIL_PANEL: print("TRAIL_DEBUG: clear_all_trails called")
    if map_canvas:
        map_canvas.delete("trail")
    initialize_robot_position() # Recenter static map icon
    initialize_trail_display() # Clears history and trail canvas items (including manual objects)
    # Manual objects are cleared by initialize_trail_display via trail_canvas.delete("all")

def redraw_trail_on_panel(event=None):
    """Draws the accumulated movement history on the trail_canvas."""
    global trail_canvas, movement_history, TRAIL_SCALE
    # REMOVED: last_cliff_pattern, last_cliff_type from globals

    if DEBUG_TRAIL_PANEL:
        print(f"TRAIL_DEBUG: redraw_trail_on_panel called. Event: {event}")
        if trail_canvas:
            trail_canvas.update_idletasks()
            print(f"TRAIL_DEBUG: Canvas W={trail_canvas.winfo_width()}, H={trail_canvas.winfo_height()}")
        print(f"TRAIL_DEBUG: Movement history length: {len(movement_history)}")
        # REMOVED: print for cliff state

    if not trail_canvas:
        if DEBUG_TRAIL_PANEL: print("TRAIL_DEBUG: Trail canvas not available, returning.")
        return

    try:
        trail_canvas.update_idletasks()
        canvas_width = trail_canvas.winfo_width()
        canvas_height = trail_canvas.winfo_height()
        # Keep manual objects, delete trail segments and start dot
        trail_canvas.delete("trail_segment", "trail_start_dot")
        # REMOVED: delete cliff_marker tag

        if canvas_width <= 1 or canvas_height <= 1:
            if DEBUG_TRAIL_PANEL: print(f"TRAIL_DEBUG: Canvas not ready/sized (W:{canvas_width}, H:{canvas_height}), returning from redraw.")
            return

        current_pen_x = canvas_width / 2
        current_pen_y = canvas_height / 2
        current_pen_angle_deg = 90.0
        trail_canvas.create_oval(current_pen_x - 3, current_pen_y - 3, current_pen_x + 3, current_pen_y + 3,
                                 fill="blue", outline="blue", tags="trail_start_dot")

        for i, movement in enumerate(movement_history):
            prev_pen_x, prev_pen_y = current_pen_x, current_pen_y

            if movement['type'] == 'turn':
                current_pen_angle_deg -= movement['angle'] # Apply angle fix
                current_pen_angle_deg %= 360
                if current_pen_angle_deg < 0: current_pen_angle_deg += 360
                # if DEBUG_TRAIL_PANEL: print(f"TRAIL_DEBUG: Processed turn {i+1}. New angle: {current_pen_angle_deg:.1f}")

            elif movement['type'] == 'move':
                distance_pixels = movement['distance'] * TRAIL_SCALE
                current_pen_angle_rad = math.radians(current_pen_angle_deg)
                current_pen_x += distance_pixels * math.cos(current_pen_angle_rad)
                current_pen_y -= distance_pixels * math.sin(current_pen_angle_rad)

                # if DEBUG_TRAIL_PANEL:
                #     print(f"TRAIL_DEBUG: Processing move {i+1}: dist_cm={movement['distance']:.2f}, dist_px={distance_pixels:.2f}, angle={current_pen_angle_deg:.1f}")
                #     print(f"TRAIL_DEBUG: Line from ({prev_pen_x:.1f},{prev_pen_y:.1f}) to ({current_pen_x:.1f},{current_pen_y:.1f})")

                trail_canvas.create_line(prev_pen_x, prev_pen_y, current_pen_x, current_pen_y,
                                        fill="black", width=2, arrow=tk.LAST, tags="trail_segment")

            # ---vvv--- REMOVED Cliff Marker drawing logic ---vvv---
            # ---^^^--- REMOVED Cliff Marker drawing logic ---^^^---

    except tk.TclError as e:
        if DEBUG_TRAIL_PANEL: print(f"TRAIL_DEBUG: TclError during trail panel redraw: {e}")
        pass
    except Exception as e:
        print(f"Unexpected error in redraw_trail_on_panel: {e}")

def handle_trail_click(event):
    """Draws a representation of an object where the user clicks."""
    global trail_canvas
    if trail_canvas:
        x, y = event.x, event.y
        radius = 4
        trail_canvas.create_oval(x - radius, y - radius, x + radius, y + radius,
                                 fill="red", outline="black", tags="manual_object")
        print(f"Manual object plotted at ({x}, {y}) on trail canvas.")
# ---^^^--- NEW/MODIFIED Trail Panel Functions ---^^^---


# --- GUI Setup ---
app = tk.Tk()
app.title("CyBot Control Center - Ice Cream Truck")
app.geometry("1000x750")
app.minsize(800, 600)
style = ttk.Style(); style.theme_use('clam')
connection_frame = ttk.LabelFrame(app, text="Connection"); connection_frame.pack(pady=5, padx=10, fill="x")
status_label = ttk.Label(connection_frame, text="Disconnected", foreground="red", font=("Arial", 10, "bold")); status_label.pack(side=tk.LEFT, padx=5, pady=5)
connect_button = ttk.Button(connection_frame, text="Connect", command=connect_to_cybot); connect_button.pack(side=tk.LEFT, padx=5, pady=5)
disconnect_button = ttk.Button(connection_frame, text="Disconnect", command=disconnect_from_cybot, state=tk.DISABLED); disconnect_button.pack(side=tk.LEFT, padx=5, pady=5)
control_frame = ttk.LabelFrame(app, text="Controls"); control_frame.pack(pady=5, padx=10, fill="x")
scan_button = ttk.Button(control_frame, text="Scan (m)", command=lambda: send_command(CMD_SCAN), state=tk.DISABLED); scan_button.pack(side=tk.LEFT, padx=5, pady=5)
jingle_button = ttk.Button(control_frame, text="Jingle (j)", command=lambda: send_command(CMD_JINGLE), state=tk.DISABLED); jingle_button.pack(side=tk.LEFT, padx=5, pady=5)
ttk.Label(control_frame, text="Movement: Use WASD keys").pack(side=tk.LEFT, padx=20)
paned_window = ttk.PanedWindow(app, orient=tk.HORIZONTAL); paned_window.pack(pady=10, padx=10, expand=True, fill="both")
left_pane_frame = ttk.Frame(paned_window, width=400); paned_window.add(left_pane_frame, weight=1)
raw_data_frame = ttk.LabelFrame(left_pane_frame, text="Raw Data Log"); raw_data_frame.pack(pady=5, padx=5, expand=True, fill="both")
raw_data_text = scrolledtext.ScrolledText(raw_data_frame, wrap=tk.WORD, height=15, width=45, font=("Consolas", 9)); raw_data_text.pack(expand=True, fill="both")
bottom_left_frame = ttk.Frame(left_pane_frame); bottom_left_frame.pack(pady=5, padx=5, fill="x", side=tk.BOTTOM)
sensor_frame = ttk.LabelFrame(bottom_left_frame, text="Sensor Status"); sensor_frame.pack(side=tk.LEFT, padx=(0, 5), fill="y", anchor='nw')
sensor_canvas = tk.Canvas(sensor_frame, width=200, height=200, bg="white", highlightthickness=1, highlightbackground="grey")
sensor_canvas.pack(pady=5, anchor='n')
sensor_canvas.create_oval(50, 50, 150, 150, outline="black", width=2, tags="base_robot_shape")
sensor_canvas.create_rectangle(90, 35, 110, 50, outline="black", width=2, tags="base_robot_shape")
sensor_canvas.create_oval(65, 55, 75, 65, fill="grey", outline="black", tags="cliff_l_indicator")
sensor_canvas.create_oval(85, 45, 95, 55, fill="grey", outline="black", tags="cliff_fl_indicator")
sensor_canvas.create_oval(105, 45, 115, 55, fill="grey", outline="black", tags="cliff_fr_indicator")
sensor_canvas.create_oval(125, 55, 135, 65, fill="grey", outline="black", tags="cliff_r_indicator")
cliff_signal_frame = ttk.Frame(sensor_frame)
cliff_signal_frame.pack(pady=(0, 2), anchor='n')
cliff_l_sig_label = ttk.Label(cliff_signal_frame, text="L: N/A", width=7, anchor="center"); cliff_l_sig_label.pack(side=tk.LEFT, padx=1)
cliff_fl_sig_label = ttk.Label(cliff_signal_frame, text="FL: N/A", width=7, anchor="center"); cliff_fl_sig_label.pack(side=tk.LEFT, padx=1)
cliff_fr_sig_label = ttk.Label(cliff_signal_frame, text="FR: N/A", width=7, anchor="center"); cliff_fr_sig_label.pack(side=tk.LEFT, padx=1)
cliff_r_sig_label = ttk.Label(cliff_signal_frame, text="R: N/A", width=7, anchor="center"); cliff_r_sig_label.pack(side=tk.LEFT, padx=1)
ping_label = ttk.Label(sensor_frame, text="Ping: N/A", anchor="center")
ping_label.pack(pady=(2, 5), anchor='n')
radar_frame = ttk.LabelFrame(bottom_left_frame, text="Last Scan Radar"); radar_frame.pack(side=tk.LEFT, padx=(5, 0), expand=True, fill="both")
radar_canvas = tk.Canvas(radar_frame, bg="#d0d0e0", highlightthickness=1, highlightbackground="grey"); radar_canvas.pack(expand=True, fill="both", pady=5, padx=5)
radar_canvas.bind("<Configure>", lambda e: app.after(50, draw_radar_plot))
clear_radar_button = ttk.Button(radar_frame, text="Clear Radar", command=lambda: radar_canvas.delete("ping_scan_plot", "ir_scan_plot")); clear_radar_button.pack(side=tk.BOTTOM, pady=2)

# --- Right Pane (Map and Trail Panel) ---
main_map_and_trail_frame = ttk.Frame(paned_window)
paned_window.add(main_map_and_trail_frame, weight=3)
actual_map_frame = ttk.LabelFrame(main_map_and_trail_frame, text="Test Field Map (Top-Down View)")
actual_map_frame.pack(pady=(0,5), padx=5, expand=True, fill="both", side=tk.TOP)
map_canvas = tk.Canvas(actual_map_frame, bg="lightgrey", highlightthickness=1, highlightbackground="grey")
map_canvas.pack(expand=True, fill="both")
map_canvas.bind("<Configure>", lambda e: app.after(50, draw_robot_on_map))
map_button_frame = ttk.Frame(actual_map_frame)
map_button_frame.pack(side=tk.BOTTOM, fill="x", pady=2)
clear_objects_button = ttk.Button(map_button_frame, text="Clear Objects", command=lambda: clear_map_features("detected_object"))
clear_objects_button.pack(side=tk.LEFT, padx=5)
clear_bump_button = ttk.Button(map_button_frame, text="Clear Bump Events", command=lambda: clear_map_features("bump_event"))
clear_bump_button.pack(side=tk.LEFT, padx=5)
clear_trail_button = ttk.Button(map_button_frame, text="Clear Trail", command=clear_all_trails) # Clears trail panel too
clear_trail_button.pack(side=tk.LEFT, padx=5)

trail_panel_frame = ttk.LabelFrame(main_map_and_trail_frame, text="Movement Trail")
trail_panel_frame.pack(pady=(5,0), padx=5, expand=True, fill="both", side=tk.BOTTOM)
trail_canvas = tk.Canvas(trail_panel_frame, bg="lightyellow", highlightthickness=1, highlightbackground="grey")
trail_canvas.pack(expand=True, fill="both", pady=5, padx=5)
trail_canvas.bind("<Configure>", redraw_trail_on_panel)
# ---vvv--- Bind click event for manual object plotting ---vvv---
trail_canvas.bind("<Button-1>", handle_trail_click)
# ---^^^--- Bind click event for manual object plotting ---^^^---

# ---vvv--- Simplified buttons for trail panel ---vvv---
trail_button_frame = ttk.Frame(trail_panel_frame)
trail_button_frame.pack(side=tk.BOTTOM, fill="x", pady=2)
clear_manual_obj_button = ttk.Button(trail_button_frame, text="Clear Manual Objs",
                                     command=lambda: trail_canvas.delete("manual_object") if trail_canvas else None)
clear_manual_obj_button.pack(side=tk.LEFT, padx=5)
# REMOVED: Clear Cliff Markers button
# ---^^^--- Simplified buttons for trail panel ---^^^---


# --- Initialization and Main Loop ---
def on_closing():
    if messagebox.askokcancel("Quit", "Do you want to quit?"):
        disconnect_from_cybot()
        stop_thread_flag.set()
        app.after(200, app.destroy)
app.protocol("WM_DELETE_WINDOW", on_closing)
unbind_keys()
try:
    update_sensor_status("BUMP_L=0,BUMP_R=0,CLIFF_L_SIG=0,CLIFF_FL_SIG=0,CLIFF_FR_SIG=0,CLIFF_R_SIG=0,PING=0.0,Heading=0")
    app.after(100, draw_radar_plot)
    app.after(100, initialize_robot_position)
    app.after(150, initialize_trail_display)
    app.after(200, redraw_trail_on_panel)
except Exception as e:
    print(f"ERROR during initial GUI update: {e}")
    messagebox.showerror("Startup Error", f"An error occurred during initial GUI setup:\n{e}")
app.mainloop()
# --- Cleanup ---
print("Application closing.")
stop_thread_flag.set()