/**************************************************************************************************
* \brief 		TODO
* \copyright   SKF
**************************************************************************************************/

/* INCLUDE FILES *********************************************************************************/
#include <stdbool.h>
#include "gatt_server_interface.h"
#include "fsl_os_abstraction.h"
#include "lwrb/lwrb.h"
#include "cli.h"

/* DEFINES ***************************************************************************************/
#define BLE_GATT_SERVER_BUFFER_SIZE        (5*sizeof(gattServerEvent_t))
#define MAX_GENERIC_CALLBACKS              (20)
/* MACROS ****************************************************************************************/

/* TYPES *****************************************************************************************/
typedef struct 
{
    bool isUsed;
    gattServerEventType_t eventType;
    gattServerCallback_t callback;
} gattServerCallbackEntry_t;

/* VARIABLE DECLARATIONS *************************************************************************/
osaEventId_t  BleGattServer_Event;

static uint8_t BleGattServer_Buffer[BLE_GATT_SERVER_BUFFER_SIZE];
static lwrb_t BleGattServer_BufferLwrb;

static gattServerCallbackEntry_t BleGattServer_CallbacksEntry[MAX_GENERIC_CALLBACKS];

/* FUNCTION PROTOTYPES ***************************************************************************/
static void BleGattServer_eventManager(void);
static void BleGattServer_invokeCallback(gattServerEvent_t* gattServerEvent);
static void BleGattServer_Task(void* argument);
static void BleGattServer_Callback(deviceId_t deviceId, gattServerEvent_t* pServerEvent);
OSA_TASK_DEFINE(BleGattServer_Task,  gBleGattServerTaskPriority_c,   1, gBleGattServerTaskStackSize_c,   0);

/* FUNCTION BODY *********************************************************************************/
void BleGattServer_Init(void) {
    lwrb_init(&BleGattServer_BufferLwrb, BleGattServer_Buffer, BLE_GATT_SERVER_BUFFER_SIZE);
    BleGattServer_Event = OSA_EventCreate(TRUE);
    OSA_TaskCreate(OSA_TASK(BleGattServer_Task), NULL);

    /* Register for callbacks*/
    GattServer_RegisterCallback(BleGattServer_Callback);
}

static void BleGattServer_Callback(deviceId_t deviceId, gattServerEvent_t* pServerEvent) {
    /* not taken in account device id, only one connection at a time allowed */
    lwrb_write(&BleGattServer_BufferLwrb,pServerEvent,sizeof(gattServerEvent_t));

    OSA_EventSet(BleGattServer_Event, 0x01);
}

static void BleGattServer_Task(void* argument) {
    while(1) {
        BleGattServer_eventManager();
    }
}

static void BleGattServer_eventManager(void) {
    osaEventFlags_t event;
    gattServerEvent_t gattServerEvent;
    size_t sizeAvailable;

    /* Wait for event */
    OSA_EventWait(BleGattServer_Event, osaEventFlagsAll_c, FALSE, osaWaitForever_c , &event);

    sizeAvailable = lwrb_get_full(&BleGattServer_BufferLwrb);
    if(sizeAvailable > 0) {
        lwrb_read(&BleGattServer_BufferLwrb,&gattServerEvent,sizeof(gattServerEvent_t));
        // printf("Gatt Server event received: %d\r\n", gattServerEvent.eventType);
        
        BleGattServer_invokeCallback(&gattServerEvent);

        OSA_EventSet(BleGattServer_Event, 0x01);
    }
    else
    {
        /* No more data */
    }
}

void BleGattServer_callbackRegister(gattServerEventType_t eventType, gattServerCallback_t callback) {
    for(int i = 0; i < MAX_GENERIC_CALLBACKS; i++) {
        if(BleGattServer_CallbacksEntry[i].isUsed == false) {
            BleGattServer_CallbacksEntry[i].eventType = eventType;
            BleGattServer_CallbacksEntry[i].callback = callback;
            BleGattServer_CallbacksEntry[i].isUsed = true;
            return;
        }
    }
}

static void BleGattServer_invokeCallback(gattServerEvent_t* gattServerEvent) {
    for(int i = 0; i < MAX_GENERIC_CALLBACKS; i++) {
        if(BleGattServer_CallbacksEntry[i].isUsed && BleGattServer_CallbacksEntry[i].eventType == gattServerEvent->eventType) {
            if(BleGattServer_CallbacksEntry[i].callback != NULL) {
                BleGattServer_CallbacksEntry[i].callback(0, gattServerEvent);
            }
        }
    }
}