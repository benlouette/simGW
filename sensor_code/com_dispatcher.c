/**************************************************************************************************
* \brief 		TODO
* \copyright   SKF
**************************************************************************************************/

/* INCLUDE FILES *********************************************************************************/
#include "com_session.h"
#include "com_validator.h"
#include "com_measurement.h"
#include "com_command.h"
#include "cli.h"

/* DEFINES ***************************************************************************************/

/* MACROS ****************************************************************************************/

/* TYPES *****************************************************************************************/

/* VARIABLE DECLARATIONS *************************************************************************/

/* FUNCTION PROTOTYPES ***************************************************************************/

/* FUNCTION BODY *********************************************************************************/

void com_dispatcher_routeMessage(const SKF_App_App* message) {
    // Validate header first
    if (!com_validator_isHeaderValid(message)) {
        printf("Invalid message header\n");
        return;
    }

    uint32_t message_id = message->header.message_id;

    // Route based on payload type
    switch (message->which_payload) {
        case SKF_App_App_open_session_tag:
            com_session_handleOpenSession(&message->payload.open_session, message_id);
            break;
            
        case SKF_App_App_measurement_request_tag:
            com_measurement_handleRequest(&message->payload.measurement_request, message_id);
            break;
            
        case SKF_App_App_command_tag:
            com_command_handleRequest(&message->payload.command, message_id);
            break;

        // These are sensor->gateway messages, invalid as input
        case SKF_App_App_accept_session_tag:
        case SKF_App_App_send_measurement_tag:
        case SKF_App_App_ack_tag:
        case SKF_App_App_error_tag:
            printf("Received invalid message type (sensor->GW only)\n");
            break;
            
        default:
            printf("Received unknown message type: %d\n", message->which_payload);
            break;
    }
}