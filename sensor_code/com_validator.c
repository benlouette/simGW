/**************************************************************************************************
* \brief 		TODO
* \copyright   SKF
**************************************************************************************************/

/* INCLUDE FILES *********************************************************************************/
#include "com_validator.h"
#include "com_type.h"

/* DEFINES ***************************************************************************************/

/* MACROS ****************************************************************************************/

/* TYPES *****************************************************************************************/

/* VARIABLE DECLARATIONS *************************************************************************/

/* FUNCTION PROTOTYPES ***************************************************************************/

/* FUNCTION BODY *********************************************************************************/

static bool is_overall_type(SKF_Measurement_MeasurementType type);
static bool is_twf_type(SKF_Measurement_MeasurementType type);

bool com_validator_isHeaderValid(const SKF_App_App* message) {
    if (!message->has_header) {
        return false;
    }
    
    if (message->header.version != COM_PROTOCOL_VERSION) {
        return false;
    }

    // Check fragmentation: both must be 0 (no fragmentation when GW send message)
    if (message->header.current_fragment != 0 || message->header.total_fragments != 0) {
        return false;
    }
    
    return true;
}

bool com_validator_isOnlyOverallRequested(const SKF_Measurement_measurementRequest* request) {
    if (request->measurement_count == 0) {
        return false;
    }

    for (uint32_t i = 0; i < request->measurement_count; i++) {
        if (!is_overall_type(request->measurement[i].measurement_type)) {
            return false;
        }
    }
    
    return true;
}

bool com_validator_isOnlyOneTwf(const SKF_Measurement_measurementRequest* request) {
    if (request->measurement_count != 1) {
        return false;
    }

    return is_twf_type(request->measurement[0].measurement_type);
}

static bool is_overall_type(SKF_Measurement_MeasurementType type) {
    return (type == SKF_Measurement_MeasurementType_MeasurementTypeAccelerationOverall ||
            type == SKF_Measurement_MeasurementType_MeasurementTypeVelocityOverall ||
            type == SKF_Measurement_MeasurementType_MeasurementTypeEnveloper3Overall ||
            type == SKF_Measurement_MeasurementType_MeasurementTypeTemperatureOverall);
}

static bool is_twf_type(SKF_Measurement_MeasurementType type) {
    return (type == SKF_Measurement_MeasurementType_MeasurementTypeAccelerationTwf ||
            type == SKF_Measurement_MeasurementType_MeasurementTypeVelocityTwf ||
            type == SKF_Measurement_MeasurementType_MeasurementTypeEnveloper3Twf);
}