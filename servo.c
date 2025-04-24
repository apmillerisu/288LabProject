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

//needs work
servo_cal_t servoCal(void) {
    servo_cal_t result = {rightCalVal, leftCalVal}; // Use current static values as start
    uint8_t button;
    int currentMatchVal; // Use this instead of currentDegree for adjustment
    int adjusting_limit = 0; // 0 for 0deg (Right), 1 for 180deg (Left)
    const int STEP_SIZE = 500; // How much to change matchVal per button press

    button_init();
    lcd_init(); // Assuming these are needed here

    // Start adjusting for the 0-degree (Right) position
    currentMatchVal = 0x48440; // Start with the current/default 0-deg match value
    // Set initial servo position
    TIMER1_TBPMR_R = currentMatchVal >> 16;
    TIMER1_TBMATCHR_R = currentMatchVal & 0xFFFF;
    timer_waitMillis(500); // Wait for servo to move initially

    lcd_printf("Adj 0 deg (R)\nB1(L)/B2(R):Adj\nB4:Save Match");

    while (1) {
        button = button_getButton();

        if (button == 1) { // Move Left (Towards 180 -> Lower Match Value)
            currentMatchVal -= STEP_SIZE;
            // Optional: Add clamping to prevent extreme match values if needed
            // if (currentMatchVal < MIN_POSSIBLE_MATCH) currentMatchVal = MIN_POSSIBLE_MATCH;

            // *** Update Timer Registers ***
            TIMER1_TBPMR_R = currentMatchVal >> 16;
            TIMER1_TBMATCHR_R = currentMatchVal & 0xFFFF;
            timer_waitMillis(30); // Small delay

        } else if (button == 2) { // Move Right (Towards 0 -> Higher Match Value)
            currentMatchVal += STEP_SIZE;
            //test comment
            // Optional: Add clamping
            // if (currentMatchVal > MAX_POSSIBLE_MATCH) currentMatchVal = MAX_POSSIBLE_MATCH;

            // *** Update Timer Registers ***
            TIMER1_TBPMR_R = currentMatchVal >> 16;
            TIMER1_TBMATCHR_R = currentMatchVal & 0xFFFF;
            timer_waitMillis(30); // Small delay

        } else if (button == 4) { // Save current match value
            if (adjusting_limit == 0) { // Saving 0-degree (Right) limit
                // *** Save the currentMatchVal directly ***
                result.match_0_deg = currentMatchVal;
                adjusting_limit = 1; // Switch to adjust 180-degree limit

                // Move servo to the current/default 180-deg position to start adjustment
                //currentMatchVal = 0.0015 * 16000000;
                TIMER1_TBPMR_R = currentMatchVal >> 16;
                TIMER1_TBMATCHR_R = currentMatchVal & 0xFFFF;
                timer_waitMillis(500); // Wait for servo move

                lcd_printf("Adj 180 deg (L)\nB1(L)/B2(R):Adj\nB4:Save & Exit");

            } else { // Saving 180-degree (Left) limit
                 // *** Save the currentMatchVal directly ***
                result.match_180_deg = currentMatchVal;
                lcd_printf("Cal Done:\n0d:%d\n180d:%d", result.match_0_deg, result.match_180_deg);
                timer_waitMillis(2000);
                break; // Exit calibration loop
            }
        }
        timer_waitMillis(20); // Button debounce delay
    }
    return result; // Return the struct containing the two found match values
}
