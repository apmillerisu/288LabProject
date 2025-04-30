/**
 * @file lab9_template.c
 * @author
 * Template file for CprE 288 Lab 9
 */

#include "Timer.h"
#include "lcd.h"
#include "ping_template.h"
#include "uart-interrupt.h"
#include "servo.h"
#include "adc.h"
#include "button.h"
#include "open_interface.h"
#include "movement.h"

// Uncomment or add any include directives that are needed

#warning "Possible unimplemented functions"
#define REPLACEME 0
extern volatile int command_flag;
extern volatile char receiveByte = '\0';
//int rightCalVal;
//int leftCalVal;

int main(void) {
	timer_init(); // Must be called before lcd_init(), which uses timer functions
	lcd_init();
	//uart_init(); // or uart_interrupt_init(); for interrupt version (likely for manual movement)
	uart_interrupt_init(); 
	ping_init();
	button_init();
	servo_init();
	rightCalVal = 312500;
	leftCalVal = 285500;
//    servoCal();
//    return 0;
    oi_t *sensor_data = oi_alloc();
    oi_init(sensor_data);

    setup_ice_cream_jingle();

	// YOUR CODE HERE
	int botByte;

    //botByte = uart_receive();
    int i;
	float distance;
	char distString[100];

	trigger_ice_cream_jingle();

    turnDegree(45);
    timer_waitMillis(100);
    turnDegree(135);
    timer_waitMillis(100);
    turnDegree(0);
    timer_waitMillis(500);


	for(i = 0; i<180; i+=2){
	    turnDegree(i);
	    timer_waitMillis(100);
	}

	//turnDegree(170);
//	while(1)
//	{
//
//      // YOUR CODE HERE
//	    for(i =0; i<200; i++){
//		distance = ping_getDistance();
//	    timer_waitMillis(500);
//		sprintf(distString, "Distance: %.2f\n\r", distance);
//		uart_sendStr(distString);
//	    }
//
//        if(i == 200){
//            break;
//        }
//
//	}

	oi_free(sensor_data);

}
