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
extern volatile int currentHeading;


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

    // Initialize OI stuff
    oi_t *sensor_data = oi_alloc();
    oi_init(sensor_data);
    setup_ice_cream_jingle();


    // Declare variables
    float distance;
    int i;
    int ir_raw_value;
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
