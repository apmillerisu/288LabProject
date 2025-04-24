/*
 * movement.h
 *
 *  Created on: Feb 6, 2025
 *      Author: apmiller
 */

#ifndef MOVEMENT_H_
#define MOVEMENT_H_

#include "open_interface.h"


double move_forward (oi_t *sensor_data, double distance_mm);
void navAroundObject(oi_t *sensor_data, double distance);

double move_backward (oi_t *sensor_data, double distance_mm);
double turn_right(oi_t *sensor_data, double degrees);
double turn_left(oi_t *sensor_data, double degrees);
double bumpDetect(oi_t *sensor_data);



#endif /* MOVEMENT_H_ */
