#include "Timer.h"
#include "lcd.h"
#include "ping_template.h"
#include "uart-interrupt.h"
#include "servo.h"
#include "adc.h"
#include "button.h"
#include "open_interface.h"
#include "movement.h"
#include "iceCreamSong.h"
#include <string.h> // For string manipulation
#include <stdio.h>  // For sprintf()

// Uncomment or add any include directives that are needed

#warning "Possible unimplemented functions"
#define REPLACEME 0
extern volatile int command_flag;
extern volatile char receiveByte;
extern volatile int stopFlag;
//int rightCalVal;
//int leftCalVal;
int currentHeading;

// Function to send a formatted sensor message over UART
void send_sensor_data(oi_t *sensor_data, float ping_distance) {
    char buffer[256]; // Ensure buffer is large enough

    // Updated sprintf format string using EXISTING integer signal fields
    sprintf(buffer, "STATUS:BUMP_L=%d,BUMP_R=%d,CLIFF_L_SIG=%u,CLIFF_FL_SIG=%u,CLIFF_FR_SIG=%u,CLIFF_R_SIG=%u,PING=%.2f, Heading=%d\n",
            sensor_data->bumpLeft,
            sensor_data->bumpRight,
            sensor_data->cliffLeftSignal,       // Use existing integer value
            sensor_data->cliffFrontLeftSignal,  // Use existing integer value
            sensor_data->cliffFrontRightSignal, // Use existing integer value
            sensor_data->cliffRightSignal,      // Use existing integer value
            ping_distance,
            currentHeading);
    uart_sendStr(buffer);
}

// Function to send a formatted scan data message over UART
void send_scan_data(float angle, float distance_cm, int ir_raw) {
    char buffer[128];
    if(angle > 180){
        sprintf(buffer, "SCAN: END Scan\n");
        uart_sendStr(buffer);
    } else {
        sprintf(buffer, "SCAN:ANGLE=%.2f,DIST_CM=%.2f,IR_RAW=%d\n", angle, distance_cm, ir_raw);
        uart_sendStr(buffer);
    }
}

// Function to send a simple message
void send_message(const char *message) {
    char buffer[100];
    sprintf(buffer, "INFO:%s\n", message);
    uart_sendStr(buffer);
}

void send_movemessage(float degree, float movement){
    char buffer[100];
    sprintf(buffer, "MOVE: ANGLE_DEG=%.2f,DIST_CM=%.2f\n", degree,movement);
    uart_sendStr(buffer);
}

int checkBotSensors(oi_t *sensor_data){
    uint16_t HOLE_THRESHOLD = 400; // Hole threshold
    uint16_t BORDER_THRESHOLD =  2600; //border threshold
    int stopFlag = 0;

    if (sensor_data->bumpLeft || sensor_data->bumpRight) {
                        oi_setWheels(0, 0); // Stop
                        stopFlag = 1;
                        send_message("Bump sensor triggered! Stopped.");
                        // Optional: Add reaction logic like bumpDetect(sensor_data);
            }
                   // Cliff hole detection
                    // Check if any cliff signal is below hole threshold
            else if (sensor_data->cliffLeftSignal < HOLE_THRESHOLD ||
                        sensor_data->cliffFrontLeftSignal < HOLE_THRESHOLD ||
                        sensor_data->cliffFrontRightSignal < HOLE_THRESHOLD ||
                        sensor_data->cliffRightSignal < HOLE_THRESHOLD)
                    {
                         oi_setWheels(0, 0); // Stop
                         stopFlag = 1;
                         send_message("Cliff Hole Detected! Stopped.");
                         // Optional: Add backup/turn logic here

                    } // if any cliff sensor is above border threshold
                    else if (sensor_data->cliffLeftSignal > BORDER_THRESHOLD ||
                            sensor_data->cliffFrontLeftSignal > BORDER_THRESHOLD ||
                            sensor_data->cliffFrontRightSignal > BORDER_THRESHOLD ||
                            sensor_data->cliffRightSignal > BORDER_THRESHOLD)
                    {
                       oi_setWheels(0, 0); // Stop
                       stopFlag = 1;
                       send_message("Cliff Border Detected! Stopped.");
                    } else {
                        stopFlag = 0;
                    }


    return stopFlag;
}

int main(void) {
    // Initialize hardware modules
    timer_init();
    lcd_init();
    uart_interrupt_init(); // Use interrupt-driven UART
    adc_init();
    ping_init();
    button_init();
    servo_init();
    receiveByte = '\0';

    lcd_printf("Get some ice cream");

    // Servo calibration values (adjust as needed)
//    rightCalVal = 313000; //2041-1
//    leftCalVal = 285000; //2041-1
//    rightCalVal = 311500; //2041-15
//    leftCalVal = 283500; //2041-15
//    rightCalVal = 311500; //2041-0
//    leftCalVal = 284500; //2041-0
//    rightCalVal = 311000; //2041-10
//    leftCalVal = 283000; //2041-10
//    rightCalVal = 313000; //2041-8
//    leftCalVal = 285500; //2041-8
//    rightCalVal = 312000; //2041-13
//    leftCalVal = 285500; //2041-13
    rightCalVal = 312000; //2041-12
    leftCalVal = 286000; //2041-12


//    servoCal();
//    return 0;

    // Initialize iRobot OI
    oi_t *sensor_data = oi_alloc();
    oi_init(sensor_data);
    setup_ice_cream_jingle();


    // Declare variables
    float distance;
    int i;
    int ir_raw_value; // To store the raw IR ADC value
    int stopFlag = 0;
    int ignoreSensors = 0;
    currentHeading = 0;
    double scaledDegree = 0.87;



    // Main control loop
    while (1) {
        // 1. Get sensor data
        oi_update(sensor_data);
        stopFlag = checkBotSensors(sensor_data);
        // 2. Send sensor data to the PC
        send_sensor_data(sensor_data, distance);

        // 3. Check for commands from the PC
        if (command_flag == 1) {
            // A command has been received
            command_flag = 0; // Clear the flag immediately
            //botByte = uart_receive(); //use receiveByte
            switch (receiveByte) { // Use a switch statement for multiple commands
                case 'w': // Move forward
                    if(stopFlag == 0 || ignoreSensors ==1){
                    move_forward(sensor_data, 100); // Move 100 mm (adjust as needed)
                    send_movemessage(0.0,10);
                    } else { send_message("Stop Flag set, check sensors. Cannot move forward"); }
                    break;
                case 's': // Move backward
                    move_backward(sensor_data, 100);
                    stopFlag = 0; //reset stopflag because we moved backward
                    send_movemessage(0.0,-10.0);
                    break;
                case 'a': // Turn left
                    turn_left(sensor_data, 30*scaledDegree);
                    currentHeading -=30;
                    send_movemessage(-30.0,0.0);
                    break;
                case 'd': // Turn right
                    turn_right(sensor_data, 30*scaledDegree);
                    send_movemessage(30.0,0.0);
                    currentHeading += 30;
                    break;
                case 'z': // Turn left small
                    turn_left(sensor_data, 10*scaledDegree);
                    send_movemessage(-10.0,0.0);
                    currentHeading -=10;
                    break;
                case 'c': // Turn right small
                    turn_right(sensor_data, 10*scaledDegree);
                    send_movemessage(10.0,0.0);
                    currentHeading +=10;
                    break;
                case 'm': // Perform a scan
                //something is causing issues. it is not scanning when m is pressed
                    send_message("Starting scan");
                    turnDegree(0);
                    timer_waitMillis(500); // let servo pan to right without scanning
                    for (i = 0; i <= 182; i += 2) { // Scan from 0 to 180 degrees, 2-degree steps
                        turnDegree(i);
                        timer_waitMillis(100); // Wait for servo to settle
                        distance = ping_getDistance();
                        // Get IR sensor value (assuming you have adc_read() or similar)
                        // ir_raw_value = adc_read();  // Replace with your actual ADC read function
                         //For simplicity, let's assume  ir_raw_value is between 0-4095
                        ir_raw_value = get_avgADC(2);
                        send_scan_data(i, distance, ir_raw_value); // Send scan data
                    }
                    send_message("Scan complete");
                    break;
                 case 'j':  //play ice cream song
                    trigger_ice_cream_jingle();
                    send_message("Playing ice cream song");
                    break;
                 case 'l':
                     stopFlag = 0;
                     if(ignoreSensors){
                         ignoreSensors = 0;
                     } else {
                         ignoreSensors = 1;
                     }
                     send_message("stop flag cleared, ignoring sensors, be sure of this action");
                     break;
                default:
                    send_message("Unknown command");
                    break;
            }
            receiveByte = '\0';
        }




        // Add a small delay to control loop frequency
        timer_waitMillis(100);
    }

    oi_free(sensor_data);
    return 0;
}
