
# Create com library
add_library(com STATIC)

# Add source files
target_sources(com PRIVATE
    com.c
    com_builder.c
    com_command.c
    com_decode.c
    com_dispatcher.c
    com_encode.c
    com_measurement.c
    com_session.c
    com_validator.c
)

# Add include directories
target_include_directories(com PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}
)

add_subdirectory(ble)

target_link_libraries(com PUBLIC
    nanopb
    ble
    sensor_info
)

# Set compile definitions if needed
target_compile_definitions(com PRIVATE
    # Add any driver-specific definitions here
)


#-._.-=-._.-=-._.-=-._.-=-._.-=-._.-=-._.-=-._.-=-._.-=-._.-=-._.-                                            
# ProtoBuffer (nanopb) generation
#-._.-=-._.-=-._.-=-._.-=-._.-=-._.-=-._.-=-._.-=-._.-=-._.-=-._.-
# Generate C sources from phase1.proto using nanopb generator when source .proto or .options change.
set(PHASE1_PROTO_DIR ${CMAKE_CURRENT_SOURCE_DIR}/protocol)
set(PHASE1_PROTO ${PHASE1_PROTO_DIR}/app.proto
                 ${PHASE1_PROTO_DIR}/Common.proto
                 ${PHASE1_PROTO_DIR}/command.proto
                 ${PHASE1_PROTO_DIR}/configuration.proto
                 ${PHASE1_PROTO_DIR}/fota.proto
                 ${PHASE1_PROTO_DIR}/measurement.proto
                 ${PHASE1_PROTO_DIR}/session.proto)
set(PHASE1_OPTIONS ${PHASE1_PROTO_DIR}/phase1.options)

# Expected generated files (nanopb naming convention: <name>.pb.c / <name>.pb.h)
set(PHASE1_GEN_C ${PHASE1_PROTO_DIR}/app.pb.c
                 ${PHASE1_PROTO_DIR}/Common.pb.c
                 ${PHASE1_PROTO_DIR}/command.pb.c
                 ${PHASE1_PROTO_DIR}/configuration.pb.c
                 ${PHASE1_PROTO_DIR}/fota.pb.c
                 ${PHASE1_PROTO_DIR}/measurement.pb.c
                 ${PHASE1_PROTO_DIR}/session.pb.c)
set(PHASE1_GEN_H ${PHASE1_PROTO_DIR}/app.pb.h
                 ${PHASE1_PROTO_DIR}/Common.pb.h
                 ${PHASE1_PROTO_DIR}/command.pb.h
                 ${PHASE1_PROTO_DIR}/configuration.pb.h
                 ${PHASE1_PROTO_DIR}/fota.pb.h
                 ${PHASE1_PROTO_DIR}/measurement.pb.h
                 ${PHASE1_PROTO_DIR}/session.pb.h)


find_package(Python COMPONENTS Interpreter REQUIRED)

add_custom_command(
    OUTPUT ${PHASE1_GEN_C} ${PHASE1_GEN_H}
    COMMAND ${Python_EXECUTABLE} -m nanopb.generator.nanopb_generator --proto-path=${PHASE1_PROTO_DIR} --options-file=${PHASE1_OPTIONS} ${PHASE1_PROTO}
    WORKING_DIRECTORY ${PHASE1_PROTO_DIR}
    DEPENDS ${PHASE1_PROTO} ${PHASE1_OPTIONS}
    COMMENT "Generating nanopb sources from DeviceAppBulletSensor.proto"
    VERBATIM
)

add_custom_target(generate_phase1_proto
    DEPENDS ${PHASE1_GEN_C} ${PHASE1_GEN_H}
)

# Optionally include generated files into the main target if they are not already picked up by GLOB_RECURSE
if (NOT PHASE1_GEN_C IN_LIST SOURCES)
    list(APPEND SOURCES ${PHASE1_GEN_C})
    target_sources(com PUBLIC ${PHASE1_GEN_C} ${PHASE1_GEN_H})
    target_include_directories(com PUBLIC ${PHASE1_PROTO_DIR})
endif()

# Ensure main target builds after code generation
add_dependencies(com generate_phase1_proto)
