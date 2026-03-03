/**************************************************************************************************
* \brief 		TODO
* \copyright   SKF
**************************************************************************************************/

/* INCLUDE FILES *********************************************************************************/
#include "com_decode.h"
#include "cli.h"
#include "pb.h"
#include "pb_decode.h"

/* DEFINES ***************************************************************************************/

/* MACROS ****************************************************************************************/

/* TYPES *****************************************************************************************/

/* VARIABLE DECLARATIONS *************************************************************************/

/* FUNCTION PROTOTYPES ***************************************************************************/

/* FUNCTION BODY *********************************************************************************/

bool com_decodeMessage(uint8_t* data, size_t data_length, SKF_App_App* message) {
	if (data == NULL || message == NULL || data_length == 0) {
        return false;
    }
	
	// printf("Data received:\n");
	// for(uint32_t i = 0; i < data_length; i++) {
	// 	printf("%02x ", data[i]);
	// }
	// printf("\n");
	
	#warning quick fix must be removed, otherwise the decode will fail because of the missing header
	data[0] = 0x0a;
	data[1] = 0x04;

	pb_istream_t stream = pb_istream_from_buffer(data, data_length);
	*message = (SKF_App_App)SKF_App_App_init_default;

	bool status = pb_decode(&stream, SKF_App_App_fields, message);
	if (!status) {
		printf("Decoding failed: %s\n", PB_GET_ERROR(&stream));
	} else {
	}

	return status;
}
