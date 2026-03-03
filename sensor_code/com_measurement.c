/**************************************************************************************************
* \brief 		TODO
* \copyright   SKF
**************************************************************************************************/

/* INCLUDE FILES *********************************************************************************/
#include "cli.h"
#include "com_type.h"
#include "com_session.h"
#include "com_builder.h"
#include "com_validator.h"
#include "com_encode.h"
#include "sensor_info.h"

/* DEFINES ***************************************************************************************/
#define TWF_SLICE_SIZE 192

/* MACROS ****************************************************************************************/

/* TYPES *****************************************************************************************/
// Measurement request structure
typedef struct {
    SKF_Measurement_MeasurementType types[COM_MAX_MEASUREMENTS];
    uint32_t count;
} com_measurement_request_t;

/* VARIABLE DECLARATIONS *************************************************************************/

/* FUNCTION PROTOTYPES ***************************************************************************/
static void com_measurement_sendOverall(const com_measurement_request_t* measurements, 
                                 uint32_t message_id);
static void extract_measurement_types(const SKF_Measurement_measurementRequest* request, 
                                    com_measurement_request_t* measurements);
static void com_measurement_sendTwf(SKF_Measurement_MeasurementType twf_type, 
                             uint32_t message_id);
static twf_measurement_type_t com_measurement_ConvertMeasurementTypeToTwfType(SKF_Measurement_MeasurementType com_twf_type);

/* FUNCTION BODY *********************************************************************************/

void com_measurement_handleRequest(const SKF_Measurement_measurementRequest* request, 
                                   uint32_t message_id) {
    if (com_validator_isOnlyOverallRequested(request)) {
        // Handle overall measurements
        com_measurement_request_t measurements;
        extract_measurement_types(request, &measurements);
        com_measurement_sendOverall(&measurements, message_id);
        
    } else if (com_validator_isOnlyOneTwf(request)) {
        // Handle single TWF measurement
        com_measurement_sendTwf(request->measurement[0].measurement_type, message_id);
        
    } else {
        // Invalid request - send NACK
        SKF_App_App response = SKF_App_App_init_default;
        com_builder_Header(&response, message_id);
        com_builder_AckMessage(&response, false, COM_ERROR_INVALID_MEASUREMENT_REQUEST);
        com_encodeMessageAndSend(&response);
    }
}

static void com_measurement_sendOverall(const com_measurement_request_t* measurements_request, 
                                 uint32_t message_id) {
    SKF_App_App response = SKF_App_App_init_default;
    all_measurements_t measurements; 

    sensorInfo_getMeasurementsData(&measurements);

    com_builder_Header(&response, message_id);
    com_builder_SetMeasurementMessage(&response);
    com_builder_AddCommonMetadata(&response,&measurements);

    for(uint32_t i = 0; i < measurements_request->count; i++) {
         com_builder_AddMeasurement(&response, &measurements, measurements_request->types[i]);
    }
    
    com_encodeMessageAndSend(&response);
}

static void com_measurement_sendTwf(SKF_Measurement_MeasurementType twf_type, 
                             uint32_t message_id) {
    SKF_App_App response = SKF_App_App_init_default;
    all_measurements_t measurements;
    uint32_t size = 0;
    int16_t twf_data[TWF_SLICE_SIZE/2] = {0};
    twf_measurement_type_t sensor_twf_type;
    uint32_t total_fragment = 0;
    uint32_t current_fragment = 0;

    sensorInfo_getMeasurementsData(&measurements);
    sensor_twf_type = com_measurement_ConvertMeasurementTypeToTwfType(twf_type);
    sensorInfo_getMeasurementsTwfSize(sensor_twf_type, &size);
    size = size * 2; // Convert from number of int16_t to number of bytes
    
    total_fragment = (size + TWF_SLICE_SIZE - 1) / TWF_SLICE_SIZE; // Calculate total fragments needed
    for (current_fragment = 0; current_fragment < total_fragment; current_fragment++) {
        uint32_t offset = current_fragment * TWF_SLICE_SIZE;
        uint32_t fragment_size = (size - offset) > TWF_SLICE_SIZE ? TWF_SLICE_SIZE : (size - offset);
        
        response = (SKF_App_App)SKF_App_App_init_default;
        com_builder_FragmentedHeader(&response, message_id, current_fragment + 1, total_fragment);
        com_builder_SetMeasurementMessage(&response);
        if(current_fragment == 0) {
            com_builder_AddCommonMetadata(&response, &measurements);
            com_builder_AddTwfMetadata(&response, &measurements, twf_type);
        } else {
            com_builder_AddTwfMetadata(&response, NULL, twf_type);
        }

        sensorInfo_getMeasurementsTwfSlice(sensor_twf_type, twf_data, fragment_size/2, offset);
        com_builder_AddTwfFragment(&response, (uint8_t*)twf_data, fragment_size);
        com_encodeMessageAndSend(&response);
    }    
}

static void extract_measurement_types(const SKF_Measurement_measurementRequest* request, 
                                      com_measurement_request_t* measurements) {
    measurements->count = request->measurement_count;
    for (uint32_t i = 0; i < request->measurement_count; i++) {
        measurements->types[i] = request->measurement[i].measurement_type;
    }
}

static twf_measurement_type_t com_measurement_ConvertMeasurementTypeToTwfType(SKF_Measurement_MeasurementType com_twf_type) {
    switch (com_twf_type) {
        case SKF_Measurement_MeasurementType_MeasurementTypeAccelerationTwf:
            return acceleration_twf;
        case SKF_Measurement_MeasurementType_MeasurementTypeVelocityTwf:
            return velocity_twf;
        case SKF_Measurement_MeasurementType_MeasurementTypeEnveloper3Twf:
            return enveloper3_twf;
        default:
            // Handle invalid type if necessary
            return unknown_twf;
    }
}