/**************************************************************************************************
* \brief 		TODO
* \copyright   SKF
**************************************************************************************************/

/* INCLUDE FILES *********************************************************************************/
#include "com_encode.h"
#include "cli.h"
#include "pb.h"
#include "pb_encode.h"
#include "ble.h"

/* DEFINES ***************************************************************************************/
#define COM_MAX_ENCODED_MESSAGE_SIZE 247 /* Max size of BLE frame */

/* MACROS ****************************************************************************************/

/* TYPES *****************************************************************************************/

/* VARIABLE DECLARATIONS *************************************************************************/
static uint8_t encoded_buffer[COM_MAX_ENCODED_MESSAGE_SIZE];

/* FUNCTION PROTOTYPES ***************************************************************************/

/* FUNCTION BODY *********************************************************************************/

bool com_encodeMessageAndSend(const SKF_App_App* message) {
    pb_ostream_t stream;
	bool encoding_status;
	bool status;

    stream = pb_ostream_from_buffer(encoded_buffer, sizeof(encoded_buffer));
    encoding_status = pb_encode(&stream, SKF_App_App_fields, message);
    
    if (encoding_status) {
        ble_sendData(encoded_buffer, stream.bytes_written);
        status = true;
    } else {
        status = false;
    }
	return status;
}