/**
 * Driver for ping sensor
 * @file ping.c
 * @author
 */

#include "ping_template.h"
#include "Timer.h"
#include "lcd.h"
#include <math.h>

// Global shared variables
// Use extern declarations in the header file

volatile uint32_t g_start_time = 0;
volatile uint32_t g_end_time = 0;
volatile enum{LOW, HIGH, DONE} g_state = LOW; // State of ping echo pulse

#define BIT1 0x2
#define BIT3 0x8

void ping_init (void){

  // YOUR CODE HERE
    SYSCTL_RCGCGPIO_R |= BIT1 ; //enable clock to gpio portb
    while ((SYSCTL_PRGPIO_R & BIT1) == 0) {};
    GPIO_PORTB_DEN_R |= BIT3; // digital enable portb pin 3
    GPIO_PORTB_DIR_R |= BIT3; //set direction as output
    GPIO_PORTB_DATA_R &= ~BIT3; // make sure to have data bit 4 cleared

    //interrupt setup
    //NVIC setup: set priority of TIMER3B interrupt to 1 in bits 5-7
    //NVIC_PRI1_R = (NVIC_PRI1_R & 0xFFFFFF0F) | 0x000000F0;

    //NVIC setup: enable interrupt for TIMER3B, IRQ #6, set bit 4
    NVIC_EN1_R |= 0x10;

    IntRegister(INT_TIMER3B, TIMER3B_Handler);

    IntMasterEnable();

    // Configure and enable the timer
    //TIMER3_CTL_R &= 0x9F90;
    GPIO_PORTB_AFSEL_R |= 0x8;
    GPIO_PORTB_PCTL_R |= 0x7000;
    SYSCTL_RCGCTIMER_R |= BIT3;
    while((SYSCTL_PRTIMER_R & BIT3) == 0){};
    TIMER3_CTL_R |= 0x0c00;
    TIMER3_CFG_R |= 0x4; // enable 16 bit config
    TIMER3_TBMR_R |= 0x7; // count-down, capture mode, edge-time mode
    TIMER3_TBPR_R = 0xFF; //load prescaler
    TIMER3_TBILR_R = 0xFFFF; //load timer
    TIMER3_IMR_R |= 0x400;
    TIMER3_ICR_R |= 0x0400; //clear possible interrupt
    TIMER3_CTL_R |= 0x100;//enable timer

}

void ping_trigger (void){
    g_state = LOW;
    // Disable timer and disable timer interrupt
    TIMER3_CTL_R &= ~0x100;
    TIMER3_IMR_R &= ~0x400;
    // Disable alternate function (disconnect timer from port pin)
    GPIO_PORTB_AFSEL_R &= ~0x8;

    // YOUR CODE HERE FOR PING TRIGGER/START PULSE
    GPIO_PORTB_DIR_R |= BIT3; //set direction as output
    GPIO_PORTB_DATA_R |= BIT3; //write 1 to pin (high pulse start)
    g_state = HIGH;
    timer_waitMicros(5);
    GPIO_PORTB_DATA_R &= ~BIT3; // write 0 to pin (high pulse end)
    GPIO_PORTB_DIR_R &= ~BIT3; //set direction as input
    g_state = LOW;

    // Clear an interrupt that may have been erroneously triggered
    TIMER3_ICR_R |= 0x0400;
    // Re-enable alternate function, timer interrupt, and timer
    GPIO_PORTB_AFSEL_R |= 0x8;
    TIMER3_IMR_R |= 0x400;
    TIMER3_CTL_R |= 0x100;
}

void TIMER3B_Handler(void){

  // YOUR CODE HERE
  // As needed, go back to review your interrupt handler code for the UART lab.
  // What are the first lines of code in the ISR? Regardless of the device, interrupt handling
  // includes checking the source of the interrupt and clearing the interrupt status bit.
  // Checking the source: test the MIS bit in the MIS register (is the ISR executing
  // because the input capture event happened and interrupts were enabled for that event?
  // Clearing the interrupt: set the ICR bit (so that same event doesn't trigger another interrupt)
  // The rest of the code in the ISR depends on actions needed when the event happens.

    if(TIMER3_MIS_R & 0x400){ //if interrupt happen

        TIMER3_ICR_R |= 0x0400;
        if(g_state == LOW){
            g_state = HIGH;
            g_start_time = TIMER3_TBV_R;
        } else if(g_state == HIGH){
            g_state = DONE;
            g_end_time = TIMER3_TBV_R;
            //lcd_printf("start time:%.2lu\n end time: %.2lu", g_start_time, g_end_time);
        }
        //lcd_printf("shit\n");
        //lcd_printf("start time:%.2lu\n end time: %.2lu", g_start_time, g_end_time);
        //timer_waitMillis(500); //don't call this shit in here I guess
        //update_flag = 1;


    }

}

float ping_getDistance (void){
    long pulse_width;
    int overflow = 0;
    float distance;
	uint32_t clock_period = powf(62.5,-9.0);



    // YOUR CODE HERE
    ping_trigger();
//    if(g_state == DONE){
//        overflow = g_end_time - g_start_time;
//        time_diff = ((unsigned long)overflow<<24) + g_end_time – g_start_time;
//        g_state = LOW;
//    }
	while(g_state != DONE){
		//wait until ISR done, sit here
	}
	
	if(g_start_time >= g_end_time){
		overflow = 0;
		pulse_width = g_start_time - g_end_time;
	} 
	else { // if we rolled over, add full register
		overflow =1;
		pulse_width = (g_start_time + 0x1000000) - g_end_time;
	} 
	
	float time = pulse_width / 16000000.0;

    distance =((time * 343.0) / 2.0) * 100.0;
    g_state = LOW;

	//lcd_printf("pulse width: %.2lu\nOverflow: %d\nDistance: %.2f\n", pulse_width, overflow, distance);


	return distance;
}
