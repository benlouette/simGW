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
#define BLE_ADVERTISING_BUFFER_SIZE       (5*sizeof(gapAdvertisingEvent_t))
#define MAX_GENERIC_CALLBACKS              (20)
/* MACROS ****************************************************************************************/

/* TYPES *****************************************************************************************/
typedef struct 
{
    bool isUsed;
    gapAdvertisingEventType_t eventType;
    gapAdvertisingCallback_t callback;
} advertisingCallbackEntry_t;

/* VARIABLE DECLARATIONS *************************************************************************/
osaEventId_t  BleAdvertising_Event;

static uint8_t BleApp_AdvertisingBuffer[BLE_ADVERTISING_BUFFER_SIZE];
static lwrb_t BleApp_AdvertisingBufferLwrb;

static advertisingCallbackEntry_t BleAdvertising_CallbacksEntry[MAX_GENERIC_CALLBACKS];

/* FUNCTION PROTOTYPES ***************************************************************************/
static void BleAdvertising_eventManager(void);
static void BleAdvertising_invokeCallback(gapAdvertisingEvent_t* advertisingEvent);
static void BleAdvertising_Task(void* argument);
OSA_TASK_DEFINE(BleAdvertising_Task, gBleAdvertisingTaskPriority_c,  1, gBleAdvertisingTaskStackSize_c,  0);

/* FUNCTION BODY *********************************************************************************/
void BleAdvertising_Init(void) {
    lwrb_init(&BleApp_AdvertisingBufferLwrb, BleApp_AdvertisingBuffer, BLE_ADVERTISING_BUFFER_SIZE);
    BleAdvertising_Event = OSA_EventCreate(TRUE);
    OSA_TaskCreate(OSA_TASK(BleAdvertising_Task), NULL);

}

void BleAdvertising_Callback(gapAdvertisingEvent_t* pAdvertisingEvent)
{
    lwrb_write(&BleApp_AdvertisingBufferLwrb,pAdvertisingEvent,sizeof(gapAdvertisingEvent_t));

    OSA_EventSet(BleAdvertising_Event, 0x01);
}

static void BleAdvertising_Task(void* argument) {
    while(1) {
        BleAdvertising_eventManager();
    }
}

static void BleAdvertising_eventManager(void) {
    osaEventFlags_t event;
    gapAdvertisingEvent_t AdvertisingEvent;
    size_t sizeAvailable;

    /* Wait for event */
    OSA_EventWait(BleAdvertising_Event, osaEventFlagsAll_c, FALSE, osaWaitForever_c , &event);

    sizeAvailable = lwrb_get_full(&BleApp_AdvertisingBufferLwrb);
    if(sizeAvailable > 0) {
        lwrb_read(&BleApp_AdvertisingBufferLwrb,&AdvertisingEvent,sizeof(gapAdvertisingEvent_t));
        
        // printf("Received Advertising Event: %d\r\n", AdvertisingEvent.eventType);
        BleAdvertising_invokeCallback(&AdvertisingEvent);

        OSA_EventSet(BleAdvertising_Event, 0x01);
    }
    else
    {
        /* No more data */
    }
}

void BleAdvertising_callbackRegister(gapAdvertisingEventType_t eventType, gapAdvertisingCallback_t callback) {
    for(int i = 0; i < MAX_GENERIC_CALLBACKS; i++) {
        if(!BleAdvertising_CallbacksEntry[i].isUsed) {
            BleAdvertising_CallbacksEntry[i].eventType = eventType;
            BleAdvertising_CallbacksEntry[i].callback = callback;
            BleAdvertising_CallbacksEntry[i].isUsed = true;
            return;
        }
    }
}

static void BleAdvertising_invokeCallback(gapAdvertisingEvent_t* advertisingEvent) {
    for(int i = 0; i < MAX_GENERIC_CALLBACKS; i++) {
        if( BleAdvertising_CallbacksEntry[i].isUsed && BleAdvertising_CallbacksEntry[i].eventType == advertisingEvent->eventType) {
            if (BleAdvertising_CallbacksEntry[i].callback != NULL) {
                BleAdvertising_CallbacksEntry[i].callback(advertisingEvent);
            }
        }
    }
}