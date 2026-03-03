/**************************************************************************************************
* \brief 		TODO
* \copyright   SKF
**************************************************************************************************/

/* INCLUDE FILES *********************************************************************************/
#include "com_session.h"
#include "com_type.h"
#include "sensor_info.h"
#include "com_builder.h"
#include "com_encode.h"

/* DEFINES ***************************************************************************************/

/* MACROS ****************************************************************************************/

/* TYPES *****************************************************************************************/

/* VARIABLE DECLARATIONS *************************************************************************/

/* FUNCTION PROTOTYPES ***************************************************************************/
static void com_session_sendAcceptedSession(uint32_t message_id);
static bool com_session_getAcceptSessionData(com_acceptSessionData_t* data);

/* FUNCTION BODY *********************************************************************************/

void com_session_handleOpenSession(const SKF_Session_OpenSession* request, uint32_t message_id) {
    bool stored = sensorInfo_StoreSyncTime(request->current_sync_time);
    
    if (stored) {
        com_session_sendAcceptedSession(message_id);
    } else {
        // Send NACK with error code
        SKF_App_App response = SKF_App_App_init_default;
        com_builder_Header(&response, message_id);
        com_builder_AckMessage(&response, NACK, COM_ERROR_SYNC_TIME_ERROR);
        com_encodeMessageAndSend(&response);
    }
}

static void com_session_sendAcceptedSession(uint32_t message_id) {
    SKF_App_App response = SKF_App_App_init_default;
    com_acceptSessionData_t data;

    com_builder_Header(&response, message_id);
    if (com_session_getAcceptSessionData(&data)) {
        com_builder_AcceptedSessionMessage(&response, &data);
    } else {
        com_builder_AckMessage(&response, NACK, COM_ERROR_SESSION_DATA_ERROR);
    }

    
    com_encodeMessageAndSend(&response);
}

static bool com_session_getAcceptSessionData(com_acceptSessionData_t* data) {
    data->serial[0] = 0xC4; // TODO: Get actual serial
    data->serial[1] = 0xBD;
    data->serial[2] = 0x6A;
    data->serial[3] = 0x01;
    data->serial[4] = 0x02;
    data->serial[5] = 0x03;
    data->hardware_type = SKF_Session_HardwareType_HardwareTypeCmwa6120_std; // TODO: Get actual hardware type
    data->hw_version = 0x05;    // TODO: Get actual value
    data->fw_version = 0x00010203;    // TODO: Get actual value
    data->fw_cache_version = 0x00010203;// TODO: Get actual
    data->config_hash = 0xFFFFFFFF; // TODO: Get actual value
    data->self_diag = 0x00000000; // TODO: Get actual value
    data->battery_indicator = 95;   // TODO: Get actual value
    data->rssi = -60;  // TODO: Get actual value
    return true;
}
