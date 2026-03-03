/**************************************************************************************************
* \brief 		TODO
* \copyright   SKF
**************************************************************************************************/

/* INCLUDE FILES *********************************************************************************/
#include "com_builder.h"
#include "com_type.h"

/* DEFINES ***************************************************************************************/
#define COM_PROTOCOL_VERSION 0x01

/* MACROS ****************************************************************************************/

/* TYPES *****************************************************************************************/

/* VARIABLE DECLARATIONS *************************************************************************/

/* FUNCTION PROTOTYPES ***************************************************************************/
static void set_header_common(SKF_App_App* message, uint32_t message_id);
static bool com_builder_MeasurementMessageAddVibrationMeasurement(SKF_Measurement_MeasurementData* meas_data, 
                                                            const vibration_measurement_t* data, 
                                                            SKF_Measurement_MeasurementType type);
static bool com_builder_MeasurementMessageAddTemperatureMeasurement(SKF_Measurement_MeasurementData* meas_data, 
                                        const temperature_measurement_t* data,
                                        SKF_Measurement_MeasurementType type);
static SKF_Measurement_MeasurementData* get_next_measurement_slot(SKF_App_App* message);
static void set_measurement_metadata(SKF_Measurement_MeasurementData* measurement_data,
                                     const measurement_metadata_t* metadata,
                                     SKF_Measurement_MeasurementType type);

/* FUNCTION BODY *********************************************************************************/

void com_builder_Header(SKF_App_App* message, uint32_t message_id) {
    set_header_common(message, message_id);
    message->header.current_fragment = 0;
    message->header.total_fragments = 0;
}

void com_builder_FragmentedHeader(SKF_App_App* message, uint32_t message_id, uint32_t current_fragment, uint32_t total_fragments) {
    set_header_common(message, message_id);
    message->header.current_fragment = current_fragment;
    message->header.total_fragments = total_fragments;
}

static void set_header_common(SKF_App_App* message, uint32_t message_id) {
    message->has_header = true;
    message->header.version = COM_PROTOCOL_VERSION;
    message->header.message_id = message_id;
}


void com_builder_AckMessage(SKF_App_App* message, bool ack, uint32_t error_code) {
    message->which_payload = SKF_App_App_ack_tag;

    message->payload.ack.ack = ack;
    message->payload.ack.error_code = error_code;
}

void com_builder_AcceptedSessionMessage(SKF_App_App* message, com_acceptSessionData_t* data) {
    SKF_Session_AcceptSession* session;

    message->which_payload = SKF_App_App_accept_session_tag;
    
    session = &message->payload.accept_session;

    session->hardware_type = data->hardware_type;
    session->hw_version = data->hw_version;
    
    // Serial number (MAC address)
    for(uint32_t i=0 ; i<COM_SERIAL_SIZE ; i++){
        session->serial.bytes[i] = data->serial[i];
    }
    session->serial.size = COM_SERIAL_SIZE;
    
    // Firmware versions
    session->fw_version = data->fw_version;
    session->fw_cache_version = data->fw_cache_version;
    session->config_hash = data->config_hash;
    session->self_diag = data->self_diag;
    session->battery_indicator = data->battery_indicator;
    
    // Session info
    session->has_session_info = true;
    session->session_info.which_kind = SKF_Session_SessionInfo_session_info_ble_tag;
    session->session_info.kind.session_info_ble.rssi = data->rssi;
}

void com_builder_SetMeasurementMessage(SKF_App_App* message) {
    message->which_payload = SKF_App_App_send_measurement_tag;
}

void com_builder_AddCommonMetadata(SKF_App_App* message, 
                                        const all_measurements_t* measurements) {
    
    SKF_Measurement_SendMeasurement* measurement = &message->payload.send_measurement;
    
    // Common metadata
    measurement->has_common_meta_data = true;
    measurement->common_meta_data.config_hash = measurements->common.config_hash;
    measurement->common_meta_data.time = measurements->common.time;
}

bool com_builder_AddMeasurement(SKF_App_App* message, 
                                const all_measurements_t* measurements, 
                                SKF_Measurement_MeasurementType type) {
    SKF_Measurement_MeasurementData* meas_data;
    
    meas_data = get_next_measurement_slot(message);
    if (meas_data == NULL) {
        return false;
    }

    switch (type){
        case SKF_Measurement_MeasurementType_MeasurementTypeAccelerationOverall:
            return com_builder_MeasurementMessageAddVibrationMeasurement(meas_data, &measurements->acceleration, type);
        case SKF_Measurement_MeasurementType_MeasurementTypeVelocityOverall:
            return com_builder_MeasurementMessageAddVibrationMeasurement(meas_data, &measurements->velocity, type);
        case SKF_Measurement_MeasurementType_MeasurementTypeEnveloper3Overall:
            return com_builder_MeasurementMessageAddVibrationMeasurement(meas_data, &measurements->enveloper3, type);
        case SKF_Measurement_MeasurementType_MeasurementTypeTemperatureOverall:
            return com_builder_MeasurementMessageAddTemperatureMeasurement(meas_data, &measurements->temperature, type);
        default:
            // Unsupported measurement type
            return false;
    }
}

static bool com_builder_MeasurementMessageAddVibrationMeasurement(SKF_Measurement_MeasurementData* meas_data, 
                                                            const vibration_measurement_t* data, 
                                                            SKF_Measurement_MeasurementType type) {
    set_measurement_metadata(meas_data, &data->metadata, type);
    
    meas_data->has_data = true;
    meas_data->data.which_kind = SKF_Measurement_MeasurementDataContent_measurement_overall_tag;
    meas_data->data.kind.measurement_overall.peak2peak = data->overall.peak2peak;
    meas_data->data.kind.measurement_overall.rms = data->overall.rms;
    meas_data->data.kind.measurement_overall.peak = data->overall.peak;
    meas_data->data.kind.measurement_overall.std = data->overall.std;
    meas_data->data.kind.measurement_overall.mean = data->overall.mean;

    return true;
}

static bool com_builder_MeasurementMessageAddTemperatureMeasurement(SKF_Measurement_MeasurementData* meas_data, 
                                        const temperature_measurement_t* data,
                                        SKF_Measurement_MeasurementType type) {
    set_measurement_metadata(meas_data, &data->metadata, type);
    
    meas_data->has_data = true;
    meas_data->data.which_kind = SKF_Measurement_MeasurementDataContent_int32_data_tag;
    meas_data->data.kind.int32_data = data->temperature;

    return true;
}

bool com_builder_AddTwfMetadata(SKF_App_App* message, const all_measurements_t* measurements, SKF_Measurement_MeasurementType type) {
    SKF_Measurement_MeasurementData* meas_data;
    
    meas_data = get_next_measurement_slot(message);
    if (meas_data == NULL) {
        return false;
    }

    if(measurements == NULL) {
        // If measurements is NULL, no metadata will be added, but the slot will still be reserved for the TWF fragment. 
        // This is used for fragmented messages where the first fragment contains the metadata and subsequent fragments contain the TWF data.
        return true;
    }

    switch (type) {
        case SKF_Measurement_MeasurementType_MeasurementTypeAccelerationTwf:
            set_measurement_metadata(meas_data, &measurements->acceleration.metadata, type);
            return true;
        case SKF_Measurement_MeasurementType_MeasurementTypeVelocityTwf:
            set_measurement_metadata(meas_data, &measurements->velocity.metadata, type);
            return true;
        case SKF_Measurement_MeasurementType_MeasurementTypeEnveloper3Twf:
            set_measurement_metadata(meas_data, &measurements->enveloper3.metadata, type);
            return true;
        default:
            return false;
    }
}

bool com_builder_AddTwfFragment(SKF_App_App* message,
                                uint8_t * twf_data,
                                uint32_t size) {
    if (twf_data == NULL || size == 0 || size > 256) {
        return false;
    }
    
    message->payload.send_measurement.measurement_data->has_data = true;
    message->payload.send_measurement.measurement_data->data.which_kind = SKF_Measurement_MeasurementDataContent_data_bytes_tag;
    message->payload.send_measurement.measurement_data->data.kind.data_bytes.size = size;
    memcpy(message->payload.send_measurement.measurement_data->data.kind.data_bytes.bytes, twf_data, size);

    return true;
}


static void set_measurement_metadata(SKF_Measurement_MeasurementData* measurement_data,
                                     const measurement_metadata_t* metadata,
                                     SKF_Measurement_MeasurementType type) {
    measurement_data->has_metadata = true;
    measurement_data->metadata.which_kind = SKF_Measurement_Metadata_elo_metadata_tag;
    measurement_data->metadata.kind.elo_metadata.duration = metadata->duration;
    measurement_data->metadata.kind.elo_metadata.vibration_path = type;
}

static SKF_Measurement_MeasurementData* get_next_measurement_slot(SKF_App_App* message) {
    SKF_Measurement_SendMeasurement* measurement = &message->payload.send_measurement;
    uint32_t current_count = measurement->measurement_data_count;
    
    if (current_count >= COM_MAX_MEASUREMENTS) {
        return NULL;
    }
    
    measurement->measurement_data_count++;
    return &measurement->measurement_data[current_count];
}