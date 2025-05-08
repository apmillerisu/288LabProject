/*
 * movement.c
 *
 *  Created on: Feb 6, 2025
 *      Author: apmiller
 */
#include "movement.h"
#include "open_interface.h"
#include "lcd.h"


//volatile int stopFlag = 0;


double move_forward (oi_t *sensor_data, double distance_mm){
//    uint16_t HOLE_THRESHOLD = 400; // Hole threshold
//    uint16_t BORDER_THRESHOLD = 2600; //border threshold
    double sum = 0;
    int stopFlag = 0;


    oi_setWheels(200,200);

    while(sum < distance_mm){
        oi_update(sensor_data);
        sum += sensor_data -> distance;
        stopFlag = checkBotSensors(sensor_data);
        if(stopFlag){break;}
//try with this method, if it doesn't work, uncomment below and get rid of line above
//        if(sensor_data -> bumpLeft || sensor_data -> bumpRight){
//            break;
//        } else if (sensor_data->cliffLeftSignal < HOLE_THRESHOLD ||
//            sensor_data->cliffFrontLeftSignal < HOLE_THRESHOLD ||
//            sensor_data->cliffFrontRightSignal < HOLE_THRESHOLD ||
//            sensor_data->cliffRightSignal < HOLE_THRESHOLD)
//        {
//             oi_setWheels(0, 0); // Stop
//             break;
//             //stopFlag = 1;
//             //send_message("Cliff Hole Detected! Stopped.");
//             // Optional: Add backup/turn logic here
//
//        } // if any cliff sensor is above border threshold
//        else if (sensor_data->cliffLeftSignal > BORDER_THRESHOLD ||
//                sensor_data->cliffFrontLeftSignal > BORDER_THRESHOLD ||
//                sensor_data->cliffFrontRightSignal > BORDER_THRESHOLD ||
//                sensor_data->cliffRightSignal > BORDER_THRESHOLD)
//        {
//           oi_setWheels(0, 0); // Stop
//           break;
//
//        }
    }

    oi_setWheels(0,0);

    return sum;
}

double move_backward (oi_t *sensor_data, double distance_mm){
    double sum = 0;

    oi_setWheels(-150,-150);

    while(sum > -distance_mm){
        oi_update(sensor_data);
        sum += sensor_data -> distance;
    }

    oi_setWheels(0,0);

    return sum;
}

double turn_right(oi_t *sensor_data, double degrees){
    double turn = 0.0;

    oi_setWheels(-50, 50);

    while(turn > (-degrees)){
        oi_update(sensor_data);
        turn += sensor_data -> angle;
    }
    oi_setWheels(0,0);

    return 0;
}

double turn_left(oi_t *sensor_data, double degrees){
    double turn = 0.0;

    oi_setWheels(50, -50);

    while(turn < degrees){
        oi_update(sensor_data);
        turn += sensor_data -> angle;
    }
    oi_setWheels(0,0);

    return 0;
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


void freeBot(oi_t *sensor_data){
    oi_free(sensor_data);
}
