/** ************************************************************************************************
 * \copyright   SKF 
 *************************************************************************************************/


/***************************************************************************************************
 * INCLUDE FILES
 ***************************************************************************************************/
#include <stdint.h>
#include <stdbool.h>
#include "fsl_os_abstraction.h"
#include "Messaging.h"
#include "ble_general.h"
#include "gap_types.h"
#include "gatt_server_interface.h"
#include "lwrb/lwrb.h"
#include "gatt_db_handles.h"
#include "fsl_xcvr.h"
#include "controller_interface.h"
#include "drv_isr_mgt.h"
#include "ble_controller_task_config.h"
#include "ble_host_task_config.h"
#include "gap_interface.h"
#include "PWR_Interface.h"
#include "device_info_interface.h"
#include "ble_internal.h"
#include "drv_clock.h"
#include "cli.h"
#include "com.h"

/***************************************************************************************************
 * DEFINES
 ***************************************************************************************************/

/***************************************************************************************************
 * MACROS
 ***************************************************************************************************/

/***************************************************************************************************
 * TYPES
 ***************************************************************************************************/
typedef struct advState_tag{
    bool_t      advOn;
}advState_t;

/***************************************************************************************************
 * VARIABLE DECLARATIONS
 ***************************************************************************************************/
static deviceId_t appBle_SubscribedClientId = gInvalidDeviceId_c;

static uint16_t appBle_ServiceDataTransfertHandle;

 osaEventId_t  mAppEvent;

/* Scanning and Advertising Data */
static const gapAdStructure_t advScanStruct[1] = {
  {
    .adType = gAdShortenedLocalName_c,
    .length = 11,
    .aData = (uint8_t*)"IMx-1_ELO"
  }  
};

gapAdvertisingData_t gAppAdvertisingData = 
{
    NumberOfElements(advScanStruct),
    (void *)advScanStruct
};

gapScanResponseData_t gAppScanRspData = 
{
    0,
    NULL
};

/* Default Advertising Parameters. Values can be changed at runtime 
    to align with profile requirements */
gapAdvertisingParameters_t gAdvParams = {
    /* minInterval */         (3200/20*1), /* around 100 ms (3200/20 units of 0.625 ms) */
    /* maxInterval */         (3216/20*1),
    /* advertisingType */     gAdvConnectableUndirected_c, 
    /* addressType */         gBleAddrTypePublic_c, 
    /* directedAddressType */ gBleAddrTypePublic_c, 
    /* directedAddress */     {0, 0, 0, 0, 0, 0}, 
    /* channelMap */          (gapAdvertisingChannelMapFlags_t) (gGapAdvertisingChannelMapDefault_c), 
    /* filterPolicy */        gProcessAll_c 
};

bool AppBle_GattServerNotifFull = false;

extern gapAdvertisingParameters_t gAdvParams;
extern gapAdvertisingData_t gAppAdvertisingData;
extern gapScanResponseData_t gAppScanRspData;



/* Time between the beginning of two consecutive advertising PDU's */
const uint8_t gAdvertisingPacketInterval_c = mcAdvertisingPacketInterval_c;
/* Advertising channels that are enabled for scanning operation. */
const uint8_t gScanChannelMap_c = mcScanChannelMap_c;
/* Advertising channels that are enabled for initiator scanning operation. */
const uint8_t gInitiatorChannelMap_c = mcInitiatorChannelMap_c;
/* Offset to the first instant register */
const uint16_t gOffsetToFirstInstant_c = mcOffsetToFirstInstant_c;
/* Scan FIFO lockup detection interval in milliseconds. */
uint32_t gScanFifoLockupCheckIntervalMilliSeconds = mScanFifoLockupCheckIntervalMilliSeconds_c;

/* Default value for the DTM 2 wire serial connection. Can be changed also by using Controller_SetDTMBaudrate defined in "controller_interface.h". */
const dtmBaudrate_t gDefaultDTMBaudrate = gDTM_BaudRate_115200_c;
/* Radio system clock selection. */
const uint8_t gRfSysClk26MHz_c = 0;  /* 32MHz radio clock. */

advState_t  mAdvState;
disConfig_t      disServiceConfig = {.serviceHandle = service_device_info};

osaEventId_t com_TaskEvent;

deviceId_t connectedPeerDeviceId;

/***************************************************************************************************
 * FUNCTION PROTOTYPES
 ***************************************************************************************************/

static void Ble_HwInitialize(void);
static void ble_InitializationComplete( gapGenericEvent_t* pGenericEvent);
static void ble_InitializationAdvComplete( gapGenericEvent_t* pGenericEvent);
static void ble_ReceivedData(deviceId_t deviceId, gattServerEvent_t* pServerEvent);
static void ble_Connected( deviceId_t peerDeviceId, gapConnectionEvent_t* pConnectionEvent);
static void ble_Disconnected( deviceId_t peerDeviceId, gapConnectionEvent_t* pConnectionEvent);
static void ble_ParameterUpdateRequest( deviceId_t peerDeviceId, gapConnectionEvent_t* pConnectionEvent);
static void ble_ReceivedError(deviceId_t deviceId, gattServerEvent_t* pServerEvent);
static void ble_clearError(void);
static bool ble_isErrorPending(void);

/***************************************************************************************************
 * FUNCTION BODY
 ***************************************************************************************************/
/** *****************************************************************************************
 * \brief 		Ble Initialization, will initialise the BLE stack and associated function
 * \param[in]	void
 * \return 		void
 *******************************************************************************************/
void ble_Init(void)
{
    Ble_HwInitialize();

    BleController_Init();
    BleHost_Init();

    BleGeneric_Init();
    BleGattServer_Init();
    BleAdvertising_Init();
    BleConnection_Init();

    BleGeneric_callbackRegister(gInitializationComplete_c,ble_InitializationComplete);
    BleGeneric_callbackRegister(gAdvertisingParametersSetupComplete_c,ble_InitializationAdvComplete);

    BleGattServer_callbackRegister(gEvtAttributeWrittenWithoutResponse_c,ble_ReceivedData);
    BleGattServer_callbackRegister(gEvtError_c,ble_ReceivedError);

    BleConnection_callbackRegister(gConnEvtConnected_c, ble_Connected);
    BleConnection_callbackRegister(gConnEvtDisconnected_c, ble_Disconnected);
    BleConnection_callbackRegister(gConnEvtParameterUpdateRequest_c, ble_ParameterUpdateRequest);

    com_TaskEvent = OSA_EventCreate(TRUE);
}

static void ble_InitializationComplete( gapGenericEvent_t* pGenericEvent) {
    printf("BLE Stack Initialization Complete\r\n");
    
    Gap_ReadPublicDeviceAddress();
    Gap_SetAdvertisingData(&gAppAdvertisingData, &gAppScanRspData);

    /* Start services */
    appBle_ServiceStart();
    Dis_Start(&disServiceConfig);

    Gap_SetAdvertisingParameters(&gAdvParams);
}

static void ble_InitializationAdvComplete( gapGenericEvent_t* pGenericEvent) {
    printf("BLE Stack Advertising Parameters Setup Complete\r\n");
    /* low power can be enable */
}

static void ble_ReceivedData(deviceId_t deviceId, gattServerEvent_t* pServerEvent) {
    printf("BLE Received Data: %d\r\n", pServerEvent->eventData.attributeWrittenEvent.cValueLength);
    com_newDataReceived(pServerEvent->eventData.attributeWrittenEvent.aValue,
                            pServerEvent->eventData.attributeWrittenEvent.cValueLength);
}

static void ble_Connected( deviceId_t peerDeviceId, gapConnectionEvent_t* pConnectionEvent) {
    printf("BLE Connected\r\n");
    connectedPeerDeviceId = peerDeviceId;
    Gap_EnableUpdateConnectionParameters(peerDeviceId, TRUE);
	appBle_ServiceSubscribe(peerDeviceId);
}

static void ble_Disconnected( deviceId_t peerDeviceId, gapConnectionEvent_t* pConnectionEvent) {
    printf("BLE Disconnected\r\n");
    appBle_ServiceUnsubscribe();
}

static void ble_ParameterUpdateRequest( deviceId_t peerDeviceId, gapConnectionEvent_t* pConnectionEvent) {
    printf("BLE Parameter Update Request\r\n");
    Gap_EnableUpdateConnectionParameters(peerDeviceId, TRUE);
}

static void ble_ReceivedError(deviceId_t deviceId, gattServerEvent_t* pServerEvent) {
    // printf("BLE Received Error: %d\r\n", pServerEvent->eventData.procedureError.error);
    AppBle_GattServerNotifFull = true;
}

static void ble_clearError(void) {
    AppBle_GattServerNotifFull = false;
}

static bool ble_isErrorPending(void) {
    return AppBle_GattServerNotifFull;
}

/** *****************************************************************************************
 * \brief 		Initialisation of the BLE stack and BLE peripheral
 * \param[in]	void
 * \return 		void
 *******************************************************************************************/
static void Ble_HwInitialize(void)
{
    /* BLE Radio Init */    
    XCVR_Init(BLE_MODE, DR_1MBPS);    
    XCVR_SetXtalTrim( 0x26 );

    /* Select BLE protocol on RADIO0_IRQ */
    XCVR_MISC->XCVR_CTRL = (uint32_t)((XCVR_MISC->XCVR_CTRL & (uint32_t)~(uint32_t)(
                               XCVR_CTRL_XCVR_CTRL_RADIO0_IRQ_SEL_MASK
                              )) | (uint32_t)(
                               (0 << XCVR_CTRL_XCVR_CTRL_RADIO0_IRQ_SEL_SHIFT)
                              ));
}


/** *****************************************************************************************
 * \brief 	    return if a overflow has occurs
 * \param[in]	void
 * \return 		bool: true -> Overflow detected false-> ok
 *******************************************************************************************/
bool appBle_OverFlowDetected(void)
{
    bool returnValue;
    returnValue = AppBle_GattServerNotifFull;
    AppBle_GattServerNotifFull = false;
    return returnValue;
}

bleResult_t appBle_ServiceStart(void)
{
	uint16_t  handle;
	bleResult_t result = gBleSuccess_c;

	/* reset connected device IDs */
	appBle_SubscribedClientId = gInvalidDeviceId_c;

	/* setup command status characteristic and get handle */
	result = GattDb_FindCharValueHandleInService(	service_Elo_uart,
			 										gBleUuidType128_c, 
													(bleUuid_t*) &uuid_uart_rx, 
													&handle);

	if (result == gBleSuccess_c)
	{
		/* subscribe for write notifications */
		result = GattServer_RegisterHandlesForWriteNotifications(1, &handle);
	}
	else
	{
		/* Error raise selfDiag */
	}

	GattDb_FindCharValueHandleInService(service_Elo_uart,
										gBleUuidType128_c, 
										(bleUuid_t*) &uuid_uart_tx, 
										&appBle_ServiceDataTransfertHandle);

	return result;
}

bleResult_t appBle_ServiceSubscribe(deviceId_t clientDeviceId)
{
	if (appBle_SubscribedClientId == gInvalidDeviceId_c)
	{
		appBle_SubscribedClientId = clientDeviceId;
	}

	return gBleSuccess_c;
}

bleResult_t appBle_ServiceUnsubscribe(void)
{
	appBle_SubscribedClientId = gInvalidDeviceId_c;
    return gBleSuccess_c;
}

bleResult_t appBle_ServiceUpdateDataTransfertCharacteristic(uint8_t *data, uint8_t length_u8)
{
	bleResult_t result = gBleSuccess_c;

	result = GattDb_WriteAttribute(appBle_ServiceDataTransfertHandle, length_u8, data);

	if (gBleSuccess_c == result)
	{
		/* notify connected devices */
		if (appBle_SubscribedClientId != gInvalidDeviceId_c)
		{
			result = GattServer_SendNotification(appBle_SubscribedClientId, appBle_ServiceDataTransfertHandle);
		}
		else
		{
			/* No need to send notification */
		}
	}
	else
	{
		result = gBleUnexpectedError_c;
	}

	return result;
}

void ble_StartAdvertising(void)
{
    Gap_StartAdvertising(BleAdvertising_Callback, BleConnection_Callback);
}

void ble_StopAdvertising(void)
{
    Gap_StopAdvertising();
}

void ble_Disconnect(void)
{
    Gap_Disconnect(connectedPeerDeviceId);
}

void wait_for_write(void)
{
    OSA_EventWait(com_TaskEvent, osaEventFlagsAll_c, FALSE, 100000, NULL);
}

void ble_close_connection(void) {
    OSA_EventSet(com_TaskEvent, 0x01);
}

void ble_sendData(uint8_t* data, uint16_t length) {
    
    appBle_ServiceUpdateDataTransfertCharacteristic(data, length);
    OSA_TimeDelay(1); /* let the time to other tasks a,d for NXP stack to generate error if needed */

    while (ble_isErrorPending()) {
        ble_clearError();
        OSA_TimeDelay(10); /* let time to send data */
        appBle_ServiceUpdateDataTransfertCharacteristic(data, length);
    }

}