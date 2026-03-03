# Create ble library
add_library(ble STATIC)

# Add source files
target_sources(ble PRIVATE
    ble.c
    ble_nvm.c
    ble_generic.c
    ble_GattServer.c
    ble_advertising.c
    ble_connection.c
    ble_controller.c
    ble_host.c
)

# Add include directories
target_include_directories(ble PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}
)

target_link_libraries(ble PUBLIC
    NXP_APP
    lwrb
    skf_driver
    cli
    com
)

# Set compile definitions if needed
target_compile_definitions(ble PRIVATE
    # Add any driver-specific definitions here
)