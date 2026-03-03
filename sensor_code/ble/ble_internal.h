/**************************************************************************************************
 *
 * File:        app_main.h
 * Author:      PYD
 *
 * Description:
 *
 * Copyright:   SKF
 *
 * Created on May 17, 2018
 *
 *************************************************************************************************/

#ifndef APP_BLE_INTERNAL_H_
#define APP_BLE_INTERNAL_H_

/***************************************************************************************************
 * INCLUDE FILES
 ***************************************************************************************************/
#include "ble_general.h"

/***************************************************************************************************
 * DEFINES
 ***************************************************************************************************/

/***************************************************************************************************
 * MACROS
 ***************************************************************************************************/
 
/***************************************************************************************************
 * TYPES
 ***************************************************************************************************/

/***************************************************************************************************
 * EXTERN VARIABLES
 ***************************************************************************************************/

/***************************************************************************************************
 * FUNCTION PROTOTYPES
 ***************************************************************************************************/
bleResult_t appBle_ServiceUnsubscribe(void);
bleResult_t appBle_ServiceStart(void);
bleResult_t appBle_ServiceSubscribe(deviceId_t clientDeviceId);

void BleGeneric_Init(void);
void BleGattServer_Init(void);
void BleAdvertising_Init(void);
void BleConnection_Init(void);

void BleController_Init(void);
void BleHost_Init(void);

void BleConnection_Callback(deviceId_t peerDeviceId, gapConnectionEvent_t* pConnectionEvent);
void BleAdvertising_Callback(gapAdvertisingEvent_t* pAdvertisingEvent);

void BleGeneric_callbackRegister(gapGenericEventType_t eventType, gapGenericCallback_t callback);  
void BleGattServer_callbackRegister(gattServerEventType_t eventType, gattServerCallback_t callback);
void BleAdvertising_callbackRegister(gapAdvertisingEventType_t eventType, gapAdvertisingCallback_t callback);
void BleConnection_callbackRegister(gapConnectionEventType_t eventType, gapConnectionCallback_t callback);

#endif    /* APP_BLE_INTERNAL_H_ */
