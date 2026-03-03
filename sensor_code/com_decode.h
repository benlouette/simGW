/**************************************************************************************************
* \brief 		TODO
* \copyright   SKF
**************************************************************************************************/

/* INCLUDE FILES *********************************************************************************/
#include <stdint.h>
#include <stdbool.h>
#include "app.pb.h"

/* DEFINES ***************************************************************************************/

/* MACROS ****************************************************************************************/

/* TYPES *****************************************************************************************/

/* VARIABLE DECLARATIONS *************************************************************************/

/* FUNCTION PROTOTYPES ***************************************************************************/

/* FUNCTION BODY *********************************************************************************/

/**
 * @brief Decode received protobuf data into message structure
 * @param data Raw received data buffer
 * @param data_length Length of received data
 * @param message Output message structure
 * @return true if decoding successful, false otherwise
 */
bool com_decodeMessage(uint8_t* data, size_t data_length, SKF_App_App* message);