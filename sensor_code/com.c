
#include "com.h"
#include "com_dispatcher.h"
#include "com_decode.h"
#include "cli.h"
#include "ble.h"
#include "fsl_os_abstraction.h"
#include "lwrb/lwrb.h"

#define COM_RING_BUFFER_SIZE (256U)

static osaEventId_t com_EventId;
static uint8_t com_RingBuffer[COM_RING_BUFFER_SIZE];
static lwrb_t com_RingBufferhandle;
static uint8_t com_ProcessBuffer[COM_RING_BUFFER_SIZE];


static void com_waitForEndOfCOmmunicationSlot(void);
static void com_Task(void* argument);
OSA_TASK_DEFINE(com_Task, 10, 1, 6*gMainThreadStackSize_c, 0);
static void com_MainLoop(void);
void com_waitForBleMessage(void);

void com_newDataReceived(const uint8_t* data, size_t data_length) {
    lwrb_sz_t written;
    if (data_length < COM_RING_BUFFER_SIZE) {
        written = lwrb_write(&com_RingBufferhandle, data, data_length);
        if(written == data_length) {
            OSA_EventSet(com_EventId, 0x01);
        } else {
            printf("Failed to write all received data to ring buffer\n");
        }
    } else {
        printf("Received data length exceeds ring buffer size\n");
    }
}

void com_processReceivedData(const uint8_t* data, size_t data_length) {
    printf("Data received, length: %zu\n", data_length);

    SKF_App_App message;
    
    if (com_decodeMessage(data, data_length, &message)) {
        com_dispatcher_routeMessage(&message);
    } else {
        printf("Failed to decode message\n");
    }
}

void com_communicationSlot(void)
{
	ble_StartAdvertising();
	com_waitForEndOfCOmmunicationSlot();
	ble_StopAdvertising();
}


static void com_waitForEndOfCOmmunicationSlot(void) {
	wait_for_write(); //TODO to be rework !!
}

void com_Init(void) {
    // Initialize BLE stack and peripheral
    ble_Init();
    if (!lwrb_init(&com_RingBufferhandle, com_RingBuffer, COM_RING_BUFFER_SIZE)) {
        while(1); // critical error, wait for watchdog reset
    }
    com_EventId = OSA_EventCreate(TRUE);
    (void) OSA_TaskCreate(OSA_TASK(com_Task), NULL);
}

static void com_Task(void* argument) {
    (void)argument;

    while(1) {
        com_MainLoop();
    }
}

static void com_MainLoop(void) {
    com_waitForBleMessage();
    lwrb_sz_t bytesRead = lwrb_read(&com_RingBufferhandle, com_ProcessBuffer, COM_RING_BUFFER_SIZE);
    com_processReceivedData(com_ProcessBuffer, bytesRead);
}

void com_waitForBleMessage(void) {
    OSA_EventWait(com_EventId, osaEventFlagsAll_c, FALSE, osaWaitForever_c , NULL);
}