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
//int rightCalVal;
//int leftCalVal;

// Function to send a formatted sensor message over UART
void send_sensor_data(oi_t *sensor_data, float ping_distance) {
    char buffer[256]; // Increased buffer size to handle more data
    sprintf(buffer, "STATUS:BUMP_L=%d,BUMP_R=%d,CLIFF_L=%d,CLIFF_FL=%d,CLIFF_FR=%d,CLIFF_R=%d,PING=%.2f\n",
            sensor_data->bumpLeft, sensor_data->bumpRight, sensor_data->cliffLeft,
            sensor_data->cliffFrontLeft, sensor_data->cliffFrontRight, sensor_data->cliffRight,
            ping_distance); // Added ping distance
    uart_sendStr(buffer);
}

// Function to send a formatted scan data message over UART
void send_scan_data(float angle, float distance_mm, int ir_raw) {
    char buffer[128];
    sprintf(buffer, "SCAN:ANGLE=%.2f,DIST_MM=%.2f,IR_RAW=%d\n", angle, distance_mm, ir_raw);
    uart_sendStr(buffer);
}

// Function to send a simple message
void send_message(const char *message) {
    char buffer[100];
    sprintf(buffer, "INFO:%s\n", message);
    uart_sendStr(buffer);
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

    // Servo calibration values (adjust as needed)
    rightCalVal = 313000; //2041-1
    leftCalVal = 285000; //2041-1

//    servoCal();
//    return 0;

    // Initialize iRobot OI
    oi_t *sensor_data = oi_alloc();
    oi_init(sensor_data);

    // Setup ice cream jingle
    setup_ice_cream_jingle();

    // Declare variables
    int botByte;
    float distance;
    char distString[100];
    int i;
    float angle = 0;
    int ir_raw_value; // To store the raw IR ADC value

    // Play jingle (optional)
    //trigger_ice_cream_jingle();

//    // Example of using movement functions
//     turnDegree(45);
//     timer_waitMillis(1000);
//     turnDegree(135);
//     timer_waitMillis(1000);
//     turnDegree(0);
//     timer_waitMillis(500);


    // Main control loop
    while (1) {
        // 1. Get sensor data
        oi_update(sensor_data);

        // 2. Send sensor data to the PC
        send_sensor_data(sensor_data, distance);

        // 3. Check for commands from the PC
        if (command_flag == 1) {
            // A command has been received
            command_flag = 0; // Clear the flag immediately
            //botByte = uart_receive(); //use receiveByte
            switch (receiveByte) { // Use a switch statement for multiple commands
                case 'w': // Move forward
                    move_forward(sensor_data, 100); // Move 100 mm (adjust as needed)
                    send_message("Moving forward");
                    break;
                case 's': // Move backward
                    move_backward(sensor_data, 100);
                    send_message("Moving backward");
                    break;
                case 'a': // Turn left
                    turn_left(sensor_data, 30);
                    send_message("Turning left");
                    break;
                case 'd': // Turn right
                    turn_right(sensor_data, 30);
                    send_message("Turning right");
                    break;
                case 'm': // Perform a scan
                //something is causing issues. it is not scanning when m is pressed
                    send_message("Starting scan");
                    for (i = 0; i < 180; i += 2) { // Scan from 0 to 180 degrees, 10-degree steps
                        turnDegree(i);
                        timer_waitMillis(100); // Wait for servo to settle
                        distance = ping_getDistance();
                        // Get IR sensor value (assuming you have adc_read() or similar)
                        // ir_raw_value = adc_read();  // Replace with your actual ADC read function
                         //For simplicity, let's assume  ir_raw_value is between 0-4095
                        ir_raw_value = get_ADC();
                        send_scan_data(i, distance, ir_raw_value); // Send scan data
                    }
                    send_message("Scan complete");
                    break;
                 case 'j':  //play ice cream song
                    trigger_ice_cream_jingle();
                    send_message("Playing ice cream song");
                    break;
                default:
                    send_message("Unknown command");
                    break;
            }
            receiveByte = '\0';
        }

        // 4. Obstacle avoidance (example: stop if bump sensor is triggered)
        if (sensor_data->bumpLeft || sensor_data->bumpRight) {
            oi_setWheels(0, 0); // Stop the robot
            send_message("Bump sensor triggered! Stopped.");
            bumpDetect(sensor_data);
        }

        // 5. Cliff detection (stop if cliff sensor is triggered)
        if (sensor_data->cliffLeft || sensor_data->cliffFrontLeft || sensor_data->cliffFrontRight || sensor_data->cliffRight) {
            oi_setWheels(0, 0);
            send_message("Cliff sensor triggered! Stopped.");
        }

        // Add a small delay to control loop frequency
        timer_waitMillis(100);
    }

    oi_free(sensor_data);
    return 0;
}
