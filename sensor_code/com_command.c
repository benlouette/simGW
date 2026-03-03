/**************************************************************************************************
* \brief 		TODO
* \copyright   SKF
**************************************************************************************************/

/* INCLUDE FILES *********************************************************************************/
#include "com_session.h"
#include "com_builder.h"
#include "com_encode.h"
#include "com_type.h"
#include "ble.h"

/* DEFINES ***************************************************************************************/

/* MACROS ****************************************************************************************/

/* TYPES *****************************************************************************************/

/* VARIABLE DECLARATIONS *************************************************************************/

/* FUNCTION PROTOTYPES ***************************************************************************/

/* FUNCTION BODY *********************************************************************************/

void com_command_handleRequest(const SKF_command_Command* command, uint32_t message_id) {
    SKF_App_App response = SKF_App_App_init_default;
    com_builder_Header(&response, message_id);
    
    switch (command->command) {
        case SKF_command_CommandType_CommandTypeCloseSession:
            // Send ACK before closing
            com_builder_AckMessage(&response, ACK, COM_ERROR_NONE);
            com_encodeMessageAndSend(&response);
            ble_close_connection();
            break;
            
        default:
            // Unsupported command - send NACK
            com_builder_AckMessage(&response, NACK, COM_ERROR_INVALID_COMMAND_REQUEST);
            com_encodeMessageAndSend(&response);
            break;
    }
}