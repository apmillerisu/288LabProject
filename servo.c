/*
 * servo.c
 *
 *  Created on: Apr 10, 2025
 *      Author: apmiller
 */

#include "servo.h"

#define BIT1 0x2
#define BIT5 0x20

void servo_init(void){
    SYSCTL_RCGCGPIO_R |= BIT1 ; //enable clock to gpio portb
    while ((SYSCTL_PRGPIO_R & BIT1) == 0) {}; //wait until port ready

    GPIO_PORTB_DEN_R |= BIT5; // digital enable portb pin 5
    GPIO_PORTB_DIR_R |= BIT5; //set direction as output
    GPIO_PORTB_AFSEL_R |= BIT5; // enable alternate function pin 5

    GPIO_PORTB_PCTL_R |= 0x700000; // set timer in pctl pin 5 (timer1B)

    SYSCTL_RCGCTIMER_R |= BIT1;// enable clock for timer
    while((SYSCTL_PRTIMER_R & BIT1) == 0){}; //wait until timer ready

    TIMER1_CTL_R |= 0xC00; // this is probably wrong
    TIMER1_CFG_R |= 0x4; // enable 16 bit config
    TIMER1_TBMR_R |= 0x000A; //also could be wrong

    TIMER1_TBPR_R = 0x04; //load prescaler
    TIMER1_TBILR_R = 0xE200; //load timer (combined make 0x4E200)

    //    angle -> seconds -> clock cycles
    //    90 -> 1.5 ms -> 24000 //set difference below?
    TIMER1_TBPMR_R  = 0x04;
    TIMER1_TBMATCHR_R = 0x8440;

    TIMER1_CTL_R |= 0x100;
}

//likely needs work
void turnDegree(int degree) {
    // Clamp input degree
    if (degree < 0) degree = 0;
    else if (degree > 180) degree = 180;

    // Linear interpolation using static calibration values
    float fraction = degree / 180.0;
    // Ensure floating point math for range calculation before casting
    int target_matchVal = (int)( ((float)leftCalVal - rightCalVal) * fraction) + rightCalVal;

    // Optional: Clamp target_matchVal to be strictly within the calibrated range
    int min_cal = (rightCalVal < leftCalVal) ? rightCalVal : leftCalVal;
    int max_cal = (rightCalVal > leftCalVal) ? rightCalVal : leftCalVal;
    if (target_matchVal < min_cal) target_matchVal = min_cal;
    if (target_matchVal > max_cal) target_matchVal = max_cal;

    // Load the calculated match value into the timer registers
    TIMER1_TBPMR_R = target_matchVal >> 16;
    TIMER1_TBMATCHR_R = target_matchVal & 0xFFFF;
}

servo_cal_t servoCal(void){
    uint8_t button;
    servo_cal_t result = {rightCalVal, leftCalVal};
    uint32_t matchVal = TIMER1_TBPMR_R<<16;
    matchVal += TIMER1_TBMATCHR_R;
    int step = 500; // amount to change matchval
    int calSide = 0;//0 for right side, 1 for left

    lcd_printf("Adj to right\nB1(L)/B2(R):Adj\nB4:Save Match");

    while(1){
        button = button_getButton();


        if(button == 1){
            matchVal -= step;
            TIMER1_TBPMR_R = matchVal >> 16;
            TIMER1_TBMATCHR_R = matchVal & 0xFFFF;
            timer_waitMillis(100);

        } else if(button == 2){
            matchVal += step;
            TIMER1_TBPMR_R = matchVal >> 16;
            TIMER1_TBMATCHR_R = matchVal & 0xFFFF;
            timer_waitMillis(100);

        } else if(button == 4){
            if(calSide == 0){
                calSide = 1;
                rightCalVal = matchVal;
                result.rightVal = rightCalVal;
                lcd_printf("Adj to left\nB1(L)/B2(R):Adj\nB4:Save Match");
                timer_waitMillis(200);
            } else {
                leftCalVal = matchVal;
                result.leftVal = leftCalVal;
                lcd_printf("calibration done\nRight: %d\nLeft: %d", rightCalVal, leftCalVal);
                break;
            }
        }
    }


    return result;
}
