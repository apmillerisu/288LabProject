/*
 * adc.c
 *
 *  Created on: Mar 27, 2025
 *      Author: apmiller
 */
#include "adc.h"


void adc_init(void){
    SYSCTL_RCGCADC_R |= 0x1;
    SYSCTL_RCGCGPIO_R  |= 0x2;

    while((SYSCTL_PRGPIO_R & 0x2) != 0x2){}; // wait until port ready
    GPIO_PORTB_DIR_R &= ~0x10;
    GPIO_PORTB_AFSEL_R |= 0x10;
    GPIO_PORTB_DEN_R &= ~0x10;
    GPIO_PORTB_AMSEL_R |= 0x10;

    while((SYSCTL_PRADC_R & 0x1) != 0x1){}; // wait for adc ready

    //maybe PC_R?

    ADC0_SSPRI_R = 0x0123;// sequencer 3 highest
    ADC0_ACTSS_R &= ~0x8; // disable sequencer 3
    ADC0_EMUX_R &= ~0xF000; // software trigger
    ADC0_SSMUX3_R &= ~0x000F; //setting channel
    ADC0_SSMUX3_R += 10; // setting channel
    ADC0_SSCTL3_R = 0x0006; //IE0 END0 = 1, TS0 D0 = 0
    ADC0_IM_R &= ~0x0008; // disable interrupt
    ADC0_ACTSS_R |= 0x0008; // enable sequencer
}

int get_ADC(void){
    int result;
    ADC0_PSSI_R = 0x8;
    ADC0_SAC_R |= 0x4;
    while((ADC0_RIS_R & 0x8) == 0){};

    result = ADC0_SSFIFO3_R & 0xFFF;

    ADC0_ISC_R = 0x8;

    return result;
}

//void adc_cal(void){
//
//}

