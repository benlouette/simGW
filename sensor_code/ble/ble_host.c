/**************************************************************************************************
* \brief 		TODO
* \copyright   SKF
**************************************************************************************************/

/* INCLUDE FILES *********************************************************************************/
#include "fsl_os_abstraction.h"
#include "Messaging.h"
#include "ble_host_task_config.h"

/* DEFINES ***************************************************************************************/

/* MACROS ****************************************************************************************/

/* TYPES *****************************************************************************************/

/* VARIABLE DECLARATIONS *************************************************************************/
osaTaskId_t  gHost_TaskId;
osaEventId_t gHost_TaskEvent;
msgQueue_t   gApp2Host_TaskQueue;
msgQueue_t   gHci2Host_TaskQueue;

/* FUNCTION PROTOTYPES ***************************************************************************/
extern void Host_TaskHandler(void* argument);
static void AppBle_Host_Task(osaTaskParam_t argument);
OSA_TASK_DEFINE(AppBle_Host_Task, gHost_TaskPriority_c, 1, gHost_TaskStackSize_c, FALSE);

/* FUNCTION BODY *********************************************************************************/
void BleHost_Init(void) {
    gHost_TaskEvent = OSA_EventCreate(TRUE);
   
    /* Initialization of task message queue */
    MSG_InitQueue ( &gApp2Host_TaskQueue );
    MSG_InitQueue ( &gHci2Host_TaskQueue );
    
    /* Task creation */
    gHost_TaskId = OSA_TaskCreate(OSA_TASK(AppBle_Host_Task), NULL);
}

static void AppBle_Host_Task(osaTaskParam_t argument)
{
    Host_TaskHandler((void *) NULL);    
}