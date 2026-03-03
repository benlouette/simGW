/**************************************************************************************************
* \brief 		TODO
* \copyright   SKF
**************************************************************************************************/

/* INCLUDE FILES *********************************************************************************/
#include "fsl_os_abstraction.h"
#include "ble_controller_task_config.h"
#include "controller_interface.h"
#include "drv_isr_mgt.h"

/* DEFINES ***************************************************************************************/

/* MACROS ****************************************************************************************/

/* TYPES *****************************************************************************************/

/* VARIABLE DECLARATIONS *************************************************************************/
osaTaskId_t  gControllerTaskId;
osaEventId_t mControllerTaskEvent;
uint8_t gBD_ADDR[6];
extern bool_t gEnableSingleAdvertisement;
extern bool_t gMCUSleepDuringBleEvents;

/* FUNCTION PROTOTYPES ***************************************************************************/
extern void Controller_TaskHandler(void* argument);
extern void Controller_InterruptHandler(void);
static void BleController_Task(osaTaskParam_t argument);
OSA_TASK_DEFINE(BleController_Task,  gControllerTaskPriority_c,      1, gControllerTaskStackSize_c,      FALSE);

/* FUNCTION BODY *********************************************************************************/
void BleController_Init(void) {
    mControllerTaskEvent = OSA_EventCreate(TRUE);
    gControllerTaskId = OSA_TaskCreate(OSA_TASK(BleController_Task), NULL);

    /* ISR configuration */
    DrvIsrMgt_ConfigInterrupt(RADIO_0_IRQNUMBER,SECOND_HIGHEST_PRIO,&Controller_InterruptHandler);
    DrvIsrMgt_ClearPendingIRQ(RADIO_0_IRQNUMBER);
    DrvIsrMgt_EnableIRQ(RADIO_0_IRQNUMBER);

    /* Set Default Tx Power Level */
    Controller_SetTxPowerLevel(mAdvertisingDefaultTxPower_c, gAdvTxChannel_c);
    Controller_SetTxPowerLevel(mConnectionDefaultTxPower_c, gConnTxChannel_c);

    /* Configure BD_ADDR before calling Controller_Init */
    gBD_ADDR[5] = 0xC4;
    gBD_ADDR[4] = 0xBD;
    gBD_ADDR[3] = 0x6A;
    gBD_ADDR[2] = 0x01;
    gBD_ADDR[1] = 0x02;
    gBD_ADDR[0] = 0x03;

    gEnableSingleAdvertisement = TRUE;
    gMCUSleepDuringBleEvents = cMCU_SleepDuringBleEvents;

    /* BLE Controller Init */
    Controller_Init(Ble_HciRecv);
}

static void BleController_Task(osaTaskParam_t argument)
{
    Controller_TaskHandler((void *) NULL);    
}