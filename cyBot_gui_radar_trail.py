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

# Map and Trail Constants
MAP_SCALE = 2.0 # pixels / cm (e.g., 1 meter = 100 cm = 200 pixels)
ROBOT_RADIUS_PIXELS = 15 # Approximate visual size on map

# Object Detection Constants (Tune these)
OBJECT_MAX_DIST_CM = 250.0 # Ignore points further than this for object detection
OBJECT_MIN_ANGLE_WIDTH_DEG = 4.0 # Minimum angular size to be considered an object
OBJECT_MIN_POINTS = 2 # Minimum consecutive points to form an object
OBJECT_EDGE_THRESHOLD_CM = 30.0 # Min distance change (cm) to detect edge

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
last_scan_data = [] # Stores the points (angle_deg, dist_cm, ir_adc) of the last completed scan

# --- Network Communication (Unchanged) ---
def connect_to_cybot():
    # (Same as before)
    global cybot_socket, is_connected, robot_x, robot_y, robot_angle_deg
    if is_connected: status_label.config(text="Already connected.", foreground="orange"); return
    robot_angle_deg = 90.0
    try:
        status_label.config(text=f"Connecting to {CYBOT_IP}:{CYBOT_PORT}...", foreground="black"); app.update_idletasks()
        cybot_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM); cybot_socket.settimeout(5.0)
        cybot_socket.connect((CYBOT_IP, CYBOT_PORT)); cybot_socket.settimeout(None)
        is_connected = True
        status_label.config(text="Connected to CyBot!", foreground="green")
        connect_button.config(state=tk.DISABLED); disconnect_button.config(state=tk.NORMAL)
        scan_button.config(state=tk.NORMAL); jingle_button.config(state=tk.NORMAL)
        bind_keys(); app.after(100, initialize_robot_position)
        stop_thread_flag.clear()
        listen_thread = threading.Thread(target=listen_for_messages, daemon=True); listen_thread.start()
        app.after(100, process_incoming_messages)
    except socket.timeout:
        status_label.config(text="Connection timed out.", foreground="red"); messagebox.showerror("Connection Error", f"Connection to {CYBOT_IP}:{CYBOT_PORT} timed out.")
        is_connected = False; cybot_socket = None
    except Exception as e:
        status_label.config(text=f"Connection failed: {e}", foreground="red"); messagebox.showerror("Connection Error", f"Could not connect to {CYBOT_IP}:{CYBOT_PORT}\nError: {e}")
        is_connected = False; cybot_socket = None

def disconnect_from_cybot():
    # (Same as before)
    global cybot_socket, is_connected
    if not is_connected: return
    status_label.config(text="Disconnecting...", foreground="black"); stop_thread_flag.set()
    if cybot_socket:
        try: cybot_socket.shutdown(socket.SHUT_RDWR)
        except Exception: pass
        try: cybot_socket.close()
        except Exception: pass
        finally: cybot_socket = None
    is_connected = False
    status_label.config(text="Disconnected.", foreground="red")
    connect_button.config(state=tk.NORMAL); disconnect_button.config(state=tk.DISABLED)
    scan_button.config(state=tk.DISABLED); jingle_button.config(state=tk.DISABLED)
    unbind_keys(); print("Disconnected.")

def send_command(command_to_send):
    # (Same as before)
    if not is_connected or not cybot_socket: print("Warning: Cannot send command, not connected."); return
    if not command_to_send: print("Warning: Command cannot be empty."); return
    try:
        if not command_to_send.endswith('\n'): command_to_send += '\n'
        cybot_socket.sendall(command_to_send.encode('utf-8'))
        raw_data_text.insert(tk.END, f"--> Sent: {command_to_send}")
        raw_data_text.see(tk.END)
    except Exception as e:
        status_label.config(text=f"Send failed: {e}", foreground="red")
        messagebox.showerror("Send Error", f"Failed to send command.\nError: {e}")
        app.after(0, disconnect_from_cybot)

# --- Key Binding Functions (Unchanged) ---
def handle_keypress(event):
    if app.focus_get() != raw_data_text:
        key = event.keysym.lower()
        print(f"Key pressed: {key}")
        if key == 'w': send_command(CMD_FORWARD)
        elif key == 's': send_command(CMD_BACKWARD)
        elif key == 'a': send_command(CMD_LEFT)
        elif key == 'd': send_command(CMD_RIGHT)
        elif key == 'm': send_command(CMD_SCAN)
        elif key == 'j': send_command(CMD_JINGLE)

def bind_keys():
    print("Binding keys...")
    app.bind_all('<KeyPress-w>', handle_keypress)
    app.bind_all('<KeyPress-s>', handle_keypress)
    app.bind_all('<KeyPress-a>', handle_keypress)
    app.bind_all('<KeyPress-d>', handle_keypress)
    app.bind_all('<KeyPress-m>', handle_keypress)
    app.bind_all('<KeyPress-j>', handle_keypress)

def unbind_keys():
    print("Unbinding keys...")
    app.unbind_all('<KeyPress-w>')
    app.unbind_all('<KeyPress-s>')
    app.unbind_all('<KeyPress-a>')
    app.unbind_all('<KeyPress-d>')
    app.unbind_all('<KeyPress-m>')
    app.unbind_all('<KeyPress-j>')

# --- Listener Thread and Message Processing ---

def listen_for_messages():
    # (Same as before)
    global cybot_socket, is_connected
    print("Listening thread started.")
    while not stop_thread_flag.is_set():
        try:
            cybot_socket.settimeout(0.2)
            data_bytes = cybot_socket.recv(4096)
            cybot_socket.settimeout(None)
            if data_bytes:
                message = data_bytes.decode('utf-8', errors='replace')
                message_queue.put(message)
            else:
                print("Connection closed by server (received empty data).")
                if not stop_thread_flag.is_set(): message_queue.put("CONNECTION_CLOSED")
                break
        except socket.timeout:
            continue
        except Exception as e:
            if not stop_thread_flag.is_set():
                 print(f"Socket error in listening thread: {e}")
                 message_queue.put("CONNECTION_ERROR")
            break
    print("Listening thread finished.")
    if not stop_thread_flag.is_set() and is_connected:
        app.after(0, disconnect_from_cybot)

def process_incoming_messages():
    # (Same as before, calls parse_cybot_message)
    global is_connected, stop_thread_flag
    try:
        while not message_queue.empty():
            message = message_queue.get_nowait()
            if message == "CONNECTION_CLOSED":
                 if is_connected: messagebox.showinfo("Connection Info", "Connection closed by CyBot."); disconnect_from_cybot()
                 break
            elif message == "CONNECTION_ERROR":
                 if is_connected: messagebox.showerror("Connection Error", "Socket error occurred."); disconnect_from_cybot()
                 break
            else:
                timestamp = time.strftime("%H:%M:%S", time.localtime())
                raw_data_text.insert(tk.END, f"[{timestamp}] {message}")
                if not message.endswith('\n'): raw_data_text.insert(tk.END, "\n")
                raw_data_text.see(tk.END)
                parse_cybot_message(message)
    except queue.Empty:
        pass
    if is_connected or not stop_thread_flag.is_set():
         app.after(100, process_incoming_messages)

def parse_cybot_message(message):
    """Parses a message string from CyBot and calls update functions."""
    global current_scan_buffer, last_scan_data
    lines = message.strip().split('\n')
    for line in lines:
        line = line.strip()
        if not line: continue

        # print(f"Parsing: {line}") # Reduce console noise

        try:
            if line.startswith("STATUS:"):
                update_sensor_status(line[len("STATUS:"):])
            elif line.startswith("SCAN:"): # Handles data from REAL CyBot
                if "END" in line:
                     print("Scan Finished. Processing objects...")
                     last_scan_data = current_scan_buffer[:]
                     current_scan_buffer = []
                     draw_radar_plot() # Update radar with completed scan
                     detect_and_plot_objects(last_scan_data) # Process scan for objects on map
                else:
                     # Append data, but DO NOT plot individual points on map anymore
                     append_scan_data(line[len("SCAN:"):], is_mock_data=False)
                     # update_map_with_scan(line[len("SCAN:"):]) # REMOVED real-time map plotting
            elif line.startswith("MOVE:"):
                 update_robot_position_and_trail(line[len("MOVE:"):])
            elif line.startswith("BUMP_EVENT:"):
                 update_map_with_bump(line[len("BUMP_EVENT:"):])
            elif line.startswith("INFO:") or line.startswith("DEBUG:") or line.startswith("ERROR:") or line.startswith("ACK:"):
                 pass # Just log these
            # --- Check for MOCK SERVER data format ---
            elif not line.startswith("Angle") and len(line.split()) >= 2:
                 append_scan_data(line, is_mock_data=True) # Still append for testing radar
            elif "END" in line: # Catch END from mock server too
                 print("Mock Scan Finished. Processing objects...")
                 if current_scan_buffer:
                    last_scan_data = current_scan_buffer[:]
                    current_scan_buffer = []
                    draw_radar_plot() # Update radar with mock data
                    detect_and_plot_objects(last_scan_data) # Process mock data for objects
            # else:
            #     print(f"Unparsed message: {line}")

        except Exception as e:
            print(f"Error parsing line '{line}': {e}")


# --- GUI Update Functions ---

def initialize_robot_position():
    # (Same as before)
    global robot_x, robot_y; map_canvas.update_idletasks()
    robot_x = map_canvas.winfo_width() / 2; robot_y = map_canvas.winfo_height() / 2
    print(f"Robot initialized at: ({robot_x:.1f}, {robot_y:.1f})"); draw_robot_on_map()

def update_sensor_status(status_string):
    # (Same as before)
    sensor_canvas.delete("status_indicator")
    left_bumper_color, right_bumper_color = "grey", "grey"; cliff_l_color, cliff_fl_color, cliff_fr_color, cliff_r_color = "grey", "grey", "grey", "grey"
    cliff_l_sig_val, cliff_fl_sig_val, cliff_fr_sig_val, cliff_r_sig_val = "N/A", "N/A", "N/A", "N/A"
    try:
        parts = status_string.split(',')
        for part in parts:
            key_value = part.split('=')
            if len(key_value) == 2:
                key, value = key_value[0].strip(), key_value[1].strip()
                if value == '1':
                    if key == "BUMP_L": left_bumper_color = "red"
                    elif key == "BUMP_R": right_bumper_color = "red"
                    elif key == "CLIFF_L": cliff_l_color = "orange"
                    elif key == "CLIFF_FL": cliff_fl_color = "orange"
                    elif key == "CLIFF_FR": cliff_fr_color = "orange"
                    elif key == "CLIFF_R": cliff_r_color = "orange"
                elif key == "CLIFF_L_SIG": cliff_l_sig_val = value
                elif key == "CLIFF_FL_SIG": cliff_fl_sig_val = value
                elif key == "CLIFF_FR_SIG": cliff_fr_sig_val = value
                elif key == "CLIFF_R_SIG": cliff_r_sig_val = value
    except Exception as e:
        print(f"Error parsing status string '{status_string}': {e}"); cliff_l_sig_val, cliff_fl_sig_val, cliff_fr_sig_val, cliff_r_sig_val = "Err", "Err", "Err", "Err"
    sensor_canvas.create_line(50, 80, 70, 60, fill=left_bumper_color, width=4, tags="status_indicator")
    sensor_canvas.create_line(150, 80, 130, 60, fill=right_bumper_color, width=4, tags="status_indicator")
    sensor_canvas.create_oval(65, 55, 75, 65, fill=cliff_l_color, outline="black", tags="status_indicator")
    sensor_canvas.create_oval(85, 45, 95, 55, fill=cliff_fl_color, outline="black", tags="status_indicator")
    sensor_canvas.create_oval(105, 45, 115, 55, fill=cliff_fr_color, outline="black", tags="status_indicator")
    sensor_canvas.create_oval(125, 55, 135, 65, fill=cliff_r_color, outline="black", tags="status_indicator")
    cliff_l_sig_label.config(text=f"L: {cliff_l_sig_val}"); cliff_fl_sig_label.config(text=f"FL: {cliff_fl_sig_val}")
    cliff_fr_sig_label.config(text=f"FR: {cliff_fr_sig_val}"); cliff_r_sig_label.config(text=f"R: {cliff_r_sig_val}")


def append_scan_data(scan_data_string, is_mock_data=False):
    """ Parses scan data string (real or mock) and appends (angle, dist_cm, ir) tuple to buffer. """
    global current_scan_buffer
    try:
        angle_deg, dist_cm, ir_adc = None, None, None
        if is_mock_data:
            parts = scan_data_string.split()
            if len(parts) >= 2: angle_deg, dist_m = float(parts[0]), float(parts[1]); dist_cm = dist_m * 100.0; ir_adc = 0
            else: print(f"Could not split mock data line: '{scan_data_string}'")
        else:
            parts = scan_data_string.split(',')
            for part in parts:
                key_value = part.split('=')
                if len(key_value) == 2:
                    key, value = key_value[0].strip(), key_value[1].strip()
                    if key == "ANGLE": angle_deg = float(value)
                    elif key == "DIST_CM": dist_cm = float(value)
                    elif key == "IR_ADC": ir_adc = int(value)
        if angle_deg is not None and dist_cm is not None and ir_adc is not None:
             current_scan_buffer.append((angle_deg, dist_cm, ir_adc))
             # REMOVED map update call from here for mock data
    except ValueError as ve: print(f"ValueError converting scan data '{scan_data_string}': {ve}")
    except Exception as e: print(f"Error appending scan data '{scan_data_string}': {e}")


def update_map_with_scan(scan_data_string):
    """Placeholder - No longer plots individual points on the main map."""
    pass


def detect_and_plot_objects(scan_data):
    """Processes completed scan data to find and plot objects on the map using edge detection."""
    global robot_x, robot_y, robot_angle_deg
    map_canvas.delete("detected_object") # Clear previous objects
    print(f"Detecting objects from {len(scan_data)} scan points using edge detection...")

    if not scan_data: return

    objects = []
    current_object_points = []
    in_object = False # Flag to track if we are currently scanning across an object

    # Sort data by angle
    scan_data.sort(key=lambda p: p[0])

    # Add dummy points at start and end with large distance to handle edge cases
    scan_data_padded = [(-5.0, OBJECT_MAX_DIST_CM * 2, 0)] + scan_data + [(185.0, OBJECT_MAX_DIST_CM * 2, 0)]

    for i in range(1, len(scan_data_padded)):
        angle, dist, ir = scan_data_padded[i]
        prev_angle, prev_dist, prev_ir = scan_data_padded[i-1]

        # Check if current point is within valid detection range
        currently_near = (dist > 0 and dist <= OBJECT_MAX_DIST_CM)
        # Check if previous point was within valid detection range
        previously_near = (prev_dist > 0 and prev_dist <= OBJECT_MAX_DIST_CM)
        # Calculate distance change
        dist_change = abs(dist - prev_dist) if currently_near and previously_near else OBJECT_EDGE_THRESHOLD_CM * 2

        # --- State Machine for Object Detection ---
        if not in_object:
            # State: Currently NOT in an object
            if currently_near and (not previously_near or dist_change > OBJECT_EDGE_THRESHOLD_CM):
                # Transition: Start of a new object detected (Far->Near or Big jump within Near)
                in_object = True
                current_object_points = [(angle, dist, ir)] # Start new list
        else:
            # State: Currently IN an object
            if not currently_near:
                # Transition: End of object (Near->Far)
                in_object = False
                # Process the completed segment
                if len(current_object_points) >= OBJECT_MIN_POINTS:
                    objects.append(current_object_points)
                current_object_points = [] # Reset
            elif dist_change > OBJECT_EDGE_THRESHOLD_CM:
                 # Transition: Big jump within Near zone - End previous, start new
                 # Process the completed segment
                 if len(current_object_points) >= OBJECT_MIN_POINTS:
                     objects.append(current_object_points)
                 # Start new segment
                 current_object_points = [(angle, dist, ir)]
            else:
                 # Continuation of the current object
                 current_object_points.append((angle, dist, ir))

    print(f"Found {len(objects)} potential object segments.")

    # --- Process and Plot detected object segments ---
    plotted_objects = [] # To store calculated object properties before plotting
    for segment in objects:
        start_angle_obj = segment[0][0]
        end_angle_obj = segment[-1][0]
        angular_width = abs(end_angle_obj - start_angle_obj)

        # Filter by minimum angular width
        if angular_width >= OBJECT_MIN_ANGLE_WIDTH_DEG:
            distances = [p[1] for p in segment]
            min_dist = min(distances) if distances else 0
            dist_start = segment[0][1]
            dist_end = segment[-1][1]

            # Calculate linear width using Law of Cosines
            angle_diff_rad = math.radians(angular_width)
            linear_width = 0
            if angle_diff_rad > 0.001 and dist_start > 0 and dist_end > 0:
               term = (dist_start**2 + dist_end**2 - 2 * dist_start * dist_end * math.cos(angle_diff_rad))
               linear_width = math.sqrt(max(0, term))

            plotted_objects.append({
                'middle_angle': (start_angle_obj + end_angle_obj) / 2.0,
                'distance_cm': min_dist, # Use minimum distance for position
                'linear_width_cm': linear_width
            })

    print(f"Plotting {len(plotted_objects)} objects.")
    # --- Plot calculated objects on the map ---
    for obj in plotted_objects:
        if obj['distance_cm'] <= 0: continue

        world_angle_deg = robot_angle_deg + (obj['middle_angle'] - 90.0)
        obj_angle_world_rad = math.radians(world_angle_deg)
        obj_dist_pixels = obj['distance_cm'] * MAP_SCALE
        obj_x = robot_x + obj_dist_pixels * math.cos(obj_angle_world_rad)
        obj_y = robot_y - obj_dist_pixels * math.sin(obj_angle_world_rad)

        radius_pixels = max(min(obj['linear_width_cm'] * MAP_SCALE / 2.0, 50), 3.0)

        # Draw circle representing the object - Use standard color name
        map_canvas.create_oval(obj_x - radius_pixels, obj_y - radius_pixels,
                               obj_x + radius_pixels, obj_y + radius_pixels,
                               outline="darkorange", fill="orange", width=2, tags="detected_object") # Corrected fill color
        map_canvas.create_text(obj_x, obj_y, text=f"{obj['distance_cm']:.0f}", fill="black", font=("Arial", 7), tags="detected_object")


def update_map_with_bump(bump_info_string):
    # (Same as before)
    global robot_x, robot_y, robot_angle_deg; print(f"Updating map with bump: {bump_info_string}")
    bump_offset_pixels = ROBOT_RADIUS_PIXELS; bump_angle_relative_deg = 0
    if "LEFT" in bump_info_string: bump_angle_relative_deg = 45
    elif "RIGHT" in bump_info_string: bump_angle_relative_deg = -45
    bump_angle_world_deg = robot_angle_deg + bump_angle_relative_deg
    bump_angle_world_rad = math.radians(bump_angle_world_deg)
    bump_x = robot_x + bump_offset_pixels * math.cos(bump_angle_world_rad)
    bump_y = robot_y - bump_offset_pixels * math.sin(bump_angle_world_rad)
    radius = 5
    map_canvas.create_rectangle(bump_x - radius, bump_y - radius, bump_x + radius, bump_y + radius, fill="red", outline="red", tags="bump_event")

def update_robot_position_and_trail(move_data_string):
    # (Same as before)
    global robot_x, robot_y, robot_angle_deg; print(f"Updating pose with: {move_data_string}")
    try:
        dist_cm, angle_deg_delta = 0.0, 0.0
        parts = move_data_string.split(',')
        for part in parts:
            key_value = part.split('=')
            if len(key_value) == 2:
                key, value = key_value[0].strip(), key_value[1].strip()
                if key == "DIST_CM": dist_cm = float(value)
                elif key == "ANGLE_DEG": angle_deg_delta = float(value)
        prev_x, prev_y = robot_x, robot_y
        dist_pixels = dist_cm * MAP_SCALE
        robot_angle_rad = math.radians(robot_angle_deg)
        delta_x = dist_pixels * math.cos(robot_angle_rad)
        delta_y = -dist_pixels * math.sin(robot_angle_rad)
        robot_x += delta_x; robot_y += delta_y
        robot_angle_deg += angle_deg_delta
        robot_angle_deg %= 360
        if robot_angle_deg < 0: robot_angle_deg += 360
        print(f"  New Pose: ({robot_x:.1f}, {robot_y:.1f}), Angle: {robot_angle_deg:.1f}")
        if abs(dist_cm) > 0.1 or abs(angle_deg_delta) > 0.1:
             map_canvas.create_line(prev_x, prev_y, robot_x, robot_y, fill="darkgreen", width=2, tags="trail")
        draw_robot_on_map()
    except Exception as e:
        print(f"Error processing move data '{move_data_string}': {e}")

def draw_radar_plot():
    """Draws radar grid and last scan line, improved appearance."""
    global last_scan_data
    radar_canvas.delete("scan_plot"); radar_canvas.delete("scan_plot_grid"); radar_canvas.delete("radar_robot")
    center_x = radar_canvas.winfo_width() / 2; center_y = radar_canvas.winfo_height() / 2
    if center_x <= 1 or center_y <= 1: return
    max_radius_pixels = min(center_x, center_y) * 0.9; max_dist_cm = 300.0

    # --- Draw Grid ---
    grid_color = "#A0A0A0"; label_color = "#505050"
    # Concentric Arcs (0 to 180 degrees)
    for r_cm in [50, 100, 150, 200, 250, 300]:
        r_ratio = r_cm / max_dist_cm;
        if r_ratio > 1.0: continue
        r = max_radius_pixels * r_ratio
        radar_canvas.create_arc(center_x-r, center_y-r, center_x+r, center_y+r,
                                start=0, extent=180, outline=grid_color, style=tk.ARC, tags="scan_plot_grid")
        radar_canvas.create_text(center_x + 5, center_y - r + 8, text=f"{r_cm:.0f}", fill=label_color, font=("Arial", 7), anchor="w", tags="scan_plot_grid")

    # Radial lines every 30 degrees
    for angle_deg in range(0, 181, 30): # Changed step to 30
        angle_rad = math.radians(angle_deg); label_rad = max_radius_pixels * 1.05
        line_x = center_x + max_radius_pixels * math.cos(angle_rad); line_y = center_y - max_radius_pixels * math.sin(angle_rad)
        label_x = center_x + label_rad * math.cos(angle_rad); label_y = center_y - label_rad * math.sin(angle_rad)
        radar_canvas.create_line(center_x, center_y, line_x, line_y, fill=grid_color, tags="scan_plot_grid")
        # Adjust label position slightly based on angle
        anchor_pos = tk.CENTER; x_offset = 0; y_offset = 0
        if angle_deg == 0: anchor_pos = tk.W; x_offset = 3
        elif angle_deg == 180: anchor_pos = tk.E; x_offset = -3
        elif angle_deg == 90: anchor_pos = tk.S; y_offset = -3
        elif angle_deg < 90: anchor_pos = tk.SW; y_offset = -1; x_offset = 1
        elif angle_deg > 90: anchor_pos = tk.SE; y_offset = -1; x_offset = -1
        radar_canvas.create_text(label_x + x_offset, label_y + y_offset, text=f"{angle_deg}°", fill=label_color, font=("Arial", 8), anchor=anchor_pos, tags="scan_plot_grid")

    # --- Draw Robot Icon at Center ---
    robot_icon_size = 5
    radar_canvas.create_oval(center_x - robot_icon_size, center_y - robot_icon_size, center_x + robot_icon_size, center_y + robot_icon_size, fill="darkgreen", outline="black", tags="radar_robot")
    radar_canvas.create_line(center_x, center_y, center_x, center_y - robot_icon_size, fill="white", width=2, tags="radar_robot") # Points UP (90 deg relative)

    # --- Plot Scan Data as Line ---
    radar_points = []
    for angle_deg, dist_cm, ir_adc in last_scan_data:
        if dist_cm <= 0:
            if len(radar_points) > 1: radar_canvas.create_line(radar_points, fill="red", width=2, tags="scan_plot")
            radar_points = []
            continue
        angle_rad = math.radians(angle_deg); dist_ratio = min(dist_cm / max_dist_cm, 1.0); plot_radius = dist_ratio * max_radius_pixels
        point_x = center_x + plot_radius * math.cos(angle_rad); point_y = center_y - plot_radius * math.sin(angle_rad)
        radar_points.append(point_x); radar_points.append(point_y)
    if len(radar_points) > 1: radar_canvas.create_line(radar_points, fill="red", width=2, tags="scan_plot")

def clear_map_features(tag_to_clear):
    # Now also clears detected objects
    map_canvas.delete(tag_to_clear)
    if tag_to_clear == "trail": initialize_robot_position()


# --- GUI Setup ---
app = tk.Tk()
app.title("CyBot Control Center - Ice Cream Truck")
app.geometry("1000x750")
style = ttk.Style(); style.theme_use('clam')
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
# Main Paned Window
paned_window = ttk.PanedWindow(app, orient=tk.HORIZONTAL); paned_window.pack(pady=10, padx=10, expand=True, fill="both")
# Left Pane
left_pane_frame = ttk.Frame(paned_window, width=400); paned_window.add(left_pane_frame, weight=1)
raw_data_frame = ttk.LabelFrame(left_pane_frame, text="Raw Data Log"); raw_data_frame.pack(pady=5, padx=5, expand=True, fill="both")
raw_data_text = scrolledtext.ScrolledText(raw_data_frame, wrap=tk.WORD, height=15, width=45, font=("Consolas", 9)); raw_data_text.pack(expand=True, fill="both")
bottom_left_frame = ttk.Frame(left_pane_frame); bottom_left_frame.pack(pady=5, padx=5, fill="x", side=tk.BOTTOM)
sensor_frame = ttk.LabelFrame(bottom_left_frame, text="Sensor Status"); sensor_frame.pack(side=tk.LEFT, padx=(0, 5), fill="y")
sensor_canvas = tk.Canvas(sensor_frame, width=200, height=200, bg="white", highlightthickness=1, highlightbackground="grey"); sensor_canvas.pack(pady=5)
cliff_signal_frame = ttk.Frame(sensor_frame); cliff_signal_frame.pack(pady=(0, 5))
cliff_l_sig_label = ttk.Label(cliff_signal_frame, text="L: N/A", width=8); cliff_l_sig_label.pack(side=tk.LEFT, padx=2)
cliff_fl_sig_label = ttk.Label(cliff_signal_frame, text="FL: N/A", width=8); cliff_fl_sig_label.pack(side=tk.LEFT, padx=2)
cliff_fr_sig_label = ttk.Label(cliff_signal_frame, text="FR: N/A", width=8); cliff_fr_sig_label.pack(side=tk.LEFT, padx=2)
cliff_r_sig_label = ttk.Label(cliff_signal_frame, text="R: N/A", width=8); cliff_r_sig_label.pack(side=tk.LEFT, padx=2)
sensor_canvas.create_oval(50, 50, 150, 150, outline="black", width=2, tags="base")
sensor_canvas.create_rectangle(90, 35, 110, 50, outline="black", width=2, tags="base")
update_sensor_status("BUMP_L=0,BUMP_R=0,CLIFF_L=0,CLIFF_FL=0,CLIFF_FR=0,CLIFF_R=0,CLIFF_L_SIG=0,CLIFF_FL_SIG=0,CLIFF_FR_SIG=0,CLIFF_R_SIG=0")
radar_frame = ttk.LabelFrame(bottom_left_frame, text="Last Scan Radar"); radar_frame.pack(side=tk.LEFT, padx=(5, 0), expand=True, fill="both")
radar_canvas = tk.Canvas(radar_frame, bg="#d0d0e0", highlightthickness=1, highlightbackground="grey"); radar_canvas.pack(expand=True, fill="both", pady=5, padx=5)
radar_canvas.bind("<Configure>", lambda e: draw_radar_plot()) # Redraw radar on resize
# Clear button should only clear the scan line, not the grid or robot
clear_radar_button = ttk.Button(radar_frame, text="Clear Radar", command=lambda: radar_canvas.delete("scan_plot")); clear_radar_button.pack(side=tk.BOTTOM, pady=2)
# Right Pane
map_frame = ttk.LabelFrame(paned_window, text="Test Field Map (Top-Down View)"); paned_window.add(map_frame, weight=3)
map_canvas = tk.Canvas(map_frame, bg="lightgrey", highlightthickness=1, highlightbackground="grey"); map_canvas.pack(expand=True, fill="both")
def draw_robot_on_map(event=None):
    global robot_x, robot_y, robot_angle_deg; map_canvas.delete("robot")
    if not is_connected: return
    cx, cy = robot_x, robot_y; angle_rad = math.radians(robot_angle_deg)
    p1_x = cx + ROBOT_RADIUS_PIXELS * math.cos(angle_rad); p1_y = cy - ROBOT_RADIUS_PIXELS * math.sin(angle_rad)
    angle_left_rad = math.radians(robot_angle_deg + 150); p2_x = cx + ROBOT_RADIUS_PIXELS * 0.6 * math.cos(angle_left_rad); p2_y = cy - ROBOT_RADIUS_PIXELS * 0.6 * math.sin(angle_left_rad)
    angle_right_rad = math.radians(robot_angle_deg - 150); p3_x = cx + ROBOT_RADIUS_PIXELS * 0.6 * math.cos(angle_right_rad); p3_y = cy - ROBOT_RADIUS_PIXELS * 0.6 * math.sin(angle_right_rad)
    map_canvas.create_polygon(p1_x, p1_y, p2_x, p2_y, p3_x, p3_y, fill="darkgreen", outline="black", width=1, tags="robot")
map_canvas.bind("<Configure>", lambda e: initialize_robot_position() if not is_connected else draw_robot_on_map())
map_button_frame = ttk.Frame(map_frame); map_button_frame.pack(side=tk.BOTTOM, fill="x", pady=2)
# Renamed clear scan points button to clear detected objects
clear_objects_button = ttk.Button(map_button_frame, text="Clear Objects", command=lambda: clear_map_features("detected_object")); clear_objects_button.pack(side=tk.LEFT, padx=5)
clear_bump_button = ttk.Button(map_button_frame, text="Clear Bump Events", command=lambda: clear_map_features("bump_event")); clear_bump_button.pack(side=tk.LEFT, padx=5)
clear_trail_button = ttk.Button(map_button_frame, text="Clear Trail", command=lambda: clear_map_features("trail")); clear_trail_button.pack(side=tk.LEFT, padx=5)
# --- Main Loop ---
def on_closing():
    if messagebox.askokcancel("Quit", "Do you want to quit?"): disconnect_from_cybot(); app.after(200, app.destroy)
app.protocol("WM_DELETE_WINDOW", on_closing)
unbind_keys()
app.mainloop()
# --- Cleanup ---
print("Application closing.")
stop_thread_flag.set()

