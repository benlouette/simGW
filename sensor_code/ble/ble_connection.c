/**************************************************************************************************
* \brief 		TODO
* \copyright   SKF
**************************************************************************************************/

/* INCLUDE FILES *********************************************************************************/
#include <stdbool.h>
#include "gap_types.h"
#include "fsl_os_abstraction.h"
#include "lwrb/lwrb.h"
#include "cli.h"

/* DEFINES ***************************************************************************************/
#define BLE_CONNECTION_BUFFER_LWRB_SIZE    (5*(sizeof(gapConnectionEvent_t)+sizeof(deviceId_t)))
#define MAX_GENERIC_CALLBACKS              (20)
/* MACROS ****************************************************************************************/

/* TYPES *****************************************************************************************/
typedef struct 
{
    bool isUsed;
    gapConnectionEventType_t eventType;
    gapConnectionCallback_t callback;
} ConnectionCallbackEntry_t;

/* VARIABLE DECLARATIONS *************************************************************************/
osaEventId_t  BleConnection_Event;

static uint8_t BleConnection_Buffer[BLE_CONNECTION_BUFFER_LWRB_SIZE];
static lwrb_t BleConnection_BufferLwrb;

static ConnectionCallbackEntry_t BleConnection_CallbacksEntry[MAX_GENERIC_CALLBACKS];

/* FUNCTION PROTOTYPES ***************************************************************************/
static void BleConnection_eventManager(void);
static void BleConnection_invokeCallback(gapConnectionEvent_t* connectionEvent, deviceId_t peerDeviceId);
static void BleConnection_Task(void* argument);
OSA_TASK_DEFINE(BleConnection_Task,  gBleConnectionTaskPriority_c,   1, gBleConnectionTaskStackSize_c,   0);

/* FUNCTION BODY *********************************************************************************/
void BleConnection_Init(void) {
    lwrb_init(&BleConnection_BufferLwrb, BleConnection_Buffer, BLE_CONNECTION_BUFFER_LWRB_SIZE);
    BleConnection_Event = OSA_EventCreate(TRUE);
    OSA_TaskCreate(OSA_TASK(BleConnection_Task), NULL);
}

void BleConnection_Callback(deviceId_t peerDeviceId, gapConnectionEvent_t* pConnectionEvent)
{
    lwrb_write(&BleConnection_BufferLwrb,pConnectionEvent,sizeof(gapConnectionEvent_t));
    lwrb_write(&BleConnection_BufferLwrb,&peerDeviceId,sizeof(deviceId_t));

    OSA_EventSet(BleConnection_Event, 0x01);
}

static void BleConnection_Task(void* argument) {
    while(1) {
        BleConnection_eventManager();
    }
}

static void BleConnection_eventManager(void) {
    osaEventFlags_t event;
    gapConnectionEvent_t ConnectionEvent;
    size_t sizeAvailable;
    deviceId_t peerDeviceId;

    /* Wait for event */
    OSA_EventWait(BleConnection_Event, osaEventFlagsAll_c, FALSE, osaWaitForever_c , &event);

    sizeAvailable = lwrb_get_full(&BleConnection_BufferLwrb);
    if(sizeAvailable > 0)
    {
        lwrb_read(&BleConnection_BufferLwrb,&ConnectionEvent,sizeof(gapConnectionEvent_t));
        lwrb_read(&BleConnection_BufferLwrb,&peerDeviceId,sizeof(deviceId_t));

        // printf("Received Connection Event: %d\r\n", ConnectionEvent.eventType);
        BleConnection_invokeCallback(&ConnectionEvent, peerDeviceId);

        OSA_EventSet(BleConnection_Event, 0x01);
    }
    else
    {
        /* No more data */
    }
}

void BleConnection_callbackRegister(gapConnectionEventType_t eventType, gapConnectionCallback_t callback) {
    for(int i = 0; i < MAX_GENERIC_CALLBACKS; i++) {
        if(!BleConnection_CallbacksEntry[i].isUsed) {
            BleConnection_CallbacksEntry[i].eventType = eventType;
            BleConnection_CallbacksEntry[i].callback = callback;
            BleConnection_CallbacksEntry[i].isUsed = true;
            return;
        }
    }
}

static void BleConnection_invokeCallback(gapConnectionEvent_t* connectionEvent, deviceId_t peerDeviceId) {
    for(int i = 0; i < MAX_GENERIC_CALLBACKS; i++) {
        if(BleConnection_CallbacksEntry[i].isUsed && BleConnection_CallbacksEntry[i].eventType == connectionEvent->eventType) {
            if (BleConnection_CallbacksEntry[i].callback != NULL) {
                BleConnection_CallbacksEntry[i].callback(peerDeviceId, connectionEvent);
            }
        }
    }
}