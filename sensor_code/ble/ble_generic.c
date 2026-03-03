/**************************************************************************************************
* \brief 		TODO
* \copyright   SKF
**************************************************************************************************/

/* INCLUDE FILES *********************************************************************************/
#include <stdbool.h>
#include "ble_general.h"
#include "controller_interface.h"
#include "fsl_os_abstraction.h"
#include "lwrb/lwrb.h"

/* DEFINES ***************************************************************************************/
#define BLEAPP_GENERICBUFFER_SIZE          (5*sizeof(gapGenericEvent_t))
#define MAX_GENERIC_CALLBACKS              (20)
/* MACROS ****************************************************************************************/

/* TYPES *****************************************************************************************/
typedef struct 
{
    bool isUsed;
    gapGenericEventType_t eventType;
    gapGenericCallback_t callback;
} genericCallbackEntry_t;

/* VARIABLE DECLARATIONS *************************************************************************/
static osaEventId_t  mAppBleGenericEvent;

static uint8_t BleApp_GenericBuffer[BLEAPP_GENERICBUFFER_SIZE];
static lwrb_t BleApp_GenericBufferLwrb;

static genericCallbackEntry_t genericCallbacksRegister[MAX_GENERIC_CALLBACKS];

/* FUNCTION PROTOTYPES ***************************************************************************/
static void BleGeneric_eventManager(void);
static void BleGeneric_invokeCallback(gapGenericEvent_t* genericEvent);
static void BleGeneric_Callback(gapGenericEvent_t* pGenericEvent);
static void BleGeneric_Task(void* argument);
OSA_TASK_DEFINE(BleGeneric_Task,     gBleGenericTaskPriority_c,      1, gBleGenericTaskStackSize_c,      0);

/* FUNCTION BODY *********************************************************************************/
void BleGeneric_Init(void) {
    lwrb_init(&BleApp_GenericBufferLwrb, BleApp_GenericBuffer, BLEAPP_GENERICBUFFER_SIZE);
    mAppBleGenericEvent = OSA_EventCreate(TRUE);
    OSA_TaskCreate(OSA_TASK(BleGeneric_Task), NULL);

    /* BLE Host Stack Init */
    Ble_HostInitialize( BleGeneric_Callback, 
                        (hciHostToControllerInterface_t) Hci_SendPacketToController);
}

static void BleGeneric_Callback(gapGenericEvent_t* pGenericEvent) {
    /* save data from stack */
    lwrb_write(&BleApp_GenericBufferLwrb,pGenericEvent,sizeof(gapGenericEvent_t));

    /* Raise event */
    OSA_EventSet(mAppBleGenericEvent, 0x01);
}

static void BleGeneric_Task(void* argument) {
    while(1) {
        BleGeneric_eventManager();
    }
}

static void BleGeneric_eventManager(void) {
    osaEventFlags_t event;
    size_t sizeAvailable;
    gapGenericEvent_t genericEvent;

    /* Wait for event */
    OSA_EventWait(mAppBleGenericEvent, osaEventFlagsAll_c, FALSE, osaWaitForever_c , &event);

    sizeAvailable = lwrb_get_full(&BleApp_GenericBufferLwrb);
    if(sizeAvailable > 0) {
        lwrb_read(&BleApp_GenericBufferLwrb,&genericEvent,sizeof(gapGenericEvent_t));
        
        BleGeneric_invokeCallback(&genericEvent);

        OSA_EventSet(mAppBleGenericEvent, 0x01);
    }
    else
    {
        /* No more data */
    }
}

void BleGeneric_callbackRegister(gapGenericEventType_t eventType, gapGenericCallback_t callback) {
    for(int i = 0; i < MAX_GENERIC_CALLBACKS; i++) {
        if(genericCallbacksRegister[i].callback == NULL) {
            genericCallbacksRegister[i].eventType = eventType;
            genericCallbacksRegister[i].callback = callback;
            genericCallbacksRegister[i].isUsed = true;
            return;
        }
    }
}

static void BleGeneric_invokeCallback(gapGenericEvent_t* genericEvent) {
    for(int i = 0; i < MAX_GENERIC_CALLBACKS; i++) {
        if(genericCallbacksRegister[i].isUsed && genericCallbacksRegister[i].eventType == genericEvent->eventType) {
            if(genericCallbacksRegister[i].callback != NULL) {
                genericCallbacksRegister[i].callback(genericEvent);
            }
        }
    }
}