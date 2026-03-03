/**************************************************************************************************
* \brief 		TODO
* \copyright   SKF
**************************************************************************************************/

/* INCLUDE FILES *********************************************************************************/
#include <stdint.h>
#include <stdbool.h>
#include "app.pb.h"
#include "sensor_info.h"

/* DEFINES ***************************************************************************************/
#define COM_SERIAL_SIZE 6

/* MACROS ****************************************************************************************/

/* TYPES *****************************************************************************************/
typedef struct {
	uint8_t serial[COM_SERIAL_SIZE];
    SKF_Session_HardwareType hardware_type;
	uint32_t hw_version;
	uint32_t fw_version;
	uint32_t fw_cache_version;
	uint32_t config_hash;
	uint32_t self_diag;
	int32_t battery_indicator;
	int32_t rssi;
} com_acceptSessionData_t;


/* VARIABLE DECLARATIONS *************************************************************************/

/* FUNCTION PROTOTYPES ***************************************************************************/

/* FUNCTION BODY *********************************************************************************/

void com_builder_Header(SKF_App_App* message, uint32_t message_id);
void com_builder_FragmentedHeader(SKF_App_App* message, uint32_t message_id, uint32_t current_fragment, uint32_t total_fragments);
void com_builder_AckMessage(SKF_App_App* message, bool ack, uint32_t error_code);
void com_builder_AcceptedSessionMessage(SKF_App_App* message, com_acceptSessionData_t* data);

void com_builder_AddCommonMetadata(SKF_App_App* message, 
                                    const all_measurements_t* measurements);
bool com_builder_AddMeasurement(SKF_App_App* message, 
                                const all_measurements_t* measurements, 
                                SKF_Measurement_MeasurementType type);
void com_builder_SetMeasurementMessage(SKF_App_App* message);
bool com_builder_AddTwfMetadata(SKF_App_App* message, const all_measurements_t* measurements, SKF_Measurement_MeasurementType type);
bool com_builder_AddTwfFragment(SKF_App_App* message, uint8_t * twf_data, uint32_t size);