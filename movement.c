/*
 * movement.c
 *
 *  Created on: Feb 6, 2025
 *      Author: apmiller
 */
#include "movement.h"
#include "open_interface.h"
#include "lcd.h"


static double current_heading = 90.0;
volatile int stopFlag = 0;

double get_current_heading(void) {
    // Normalize to [0, 360)
    while (current_heading < 0)
        current_heading += 360;
    while (current_heading >= 360)
        current_heading -= 360;
    return current_heading;
}

double move_forward (oi_t *sensor_data, double distance_mm){
    uint16_t HOLE_THRESHOLD = 400; // Hole threshold
    uint16_t BORDER_THRESHOLD = 2600; //border threshold
    double sum = 0;

    oi_setWheels(200,200);

    while(sum < distance_mm){
        oi_update(sensor_data);
        sum += sensor_data -> distance;
        //lcd_printf("distance completed: %f mm", sum);
        if(sensor_data -> bumpLeft || sensor_data -> bumpRight){
            break;
        } else if (sensor_data->cliffLeftSignal < HOLE_THRESHOLD ||
            sensor_data->cliffFrontLeftSignal < HOLE_THRESHOLD ||
            sensor_data->cliffFrontRightSignal < HOLE_THRESHOLD ||
            sensor_data->cliffRightSignal < HOLE_THRESHOLD)
        {
             oi_setWheels(0, 0); // Stop
             break;
             //stopFlag = 1;
             //send_message("Cliff Hole Detected! Stopped.");
             // Optional: Add backup/turn logic here

        } // if any cliff sensor is above border threshold
        else if (sensor_data->cliffLeftSignal > BORDER_THRESHOLD ||
                sensor_data->cliffFrontLeftSignal > BORDER_THRESHOLD ||
                sensor_data->cliffFrontRightSignal > BORDER_THRESHOLD ||
                sensor_data->cliffRightSignal > BORDER_THRESHOLD)
        {
           oi_setWheels(0, 0); // Stop
           break;
//           stopFlag = 1;
//           send_message("Cliff Border Detected! Stopped.");
//        } else {
//            stopFlag = 0;
        }
    }

    oi_setWheels(0,0);

    return sum;
}

//this is what I'm currently thinking of
void navAroundObject(oi_t *sensor_data, double distance){
    double sum = 0;
    double angleTurned = 0;

    sum = move_forward(sensor_data, distance);
    if(sensor_data->bumpLeft && sensor_data->bumpRight){
        move_backward(sensor_data, 10);
        turn_right(sensor_data, 10);
        //move_forward()
    } else if(sensor_data->bumpLeft){
        move_backward(sensor_data, 10);
        turn_right(sensor_data, 10);
    } else if (sensor_data->bumpRight){
        move_backward(sensor_data, 10);
        turn_left(sensor_data, 10);
    }

}


double bumpDetect(oi_t *sensor_data){ // what to do when bumper is pressed
    double negativeDist = 0;
    if(sensor_data -> bumpLeft){
            move_backward(sensor_data, 25);
            turn_right(sensor_data, 90);
            move_forward(sensor_data, 125);
            turn_left(sensor_data, 90);
            negativeDist = 25;
    } else if(sensor_data -> bumpRight){
            move_backward(sensor_data, 25);
            turn_left(sensor_data, 90);
            move_forward(sensor_data, 125);
            turn_right(sensor_data, 90);
            negativeDist = 25;
    }
    return negativeDist; //return how much we went backwards
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
        current_heading += sensor_data->angle;
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
        current_heading += sensor_data->angle;
    }
    oi_setWheels(0,0);

    return 0;
}


void freeBot(oi_t *sensor_data){
    oi_free(sensor_data);
}
