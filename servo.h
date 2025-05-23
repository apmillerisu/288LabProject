/*
 * servo.h
 *
 *  Created on: Apr 10, 2025
 *      Author: apmiller
 */

#ifndef SERVO_H_
#define SERVO_H_

#include <stdint.h>
#include <stdbool.h>
#include <inc/tm4c123gh6pm.h>
#include "driverlib/interrupt.h"
#include "button.h"
#include "lcd.h"

int rightCalVal;
int leftCalVal;

// Structure to hold calibration results
typedef struct {
    int rightVal;
    int leftVal;
} servo_cal_t;

void servo_init(void);
servo_cal_t servoCal(void); // Modified return type
void turnDegree(int degree); // Simplified prototype

#endif /* SERVO_H_ */
