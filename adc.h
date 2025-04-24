/*
 * adc.h
 *
 *  Created on: Mar 27, 2025
 *      Author: apmiller
 */

#ifndef ADC_H_
#define ADC_H_

#include <inc/tm4c123gh6pm.h>
#include <stdint.h>

void adc_init(void);
int get_ADC(void);

#endif /* ADC_H_ */
