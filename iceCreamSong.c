#include "iceCreamSong.h"

// Define the song details
#define ICE_CREAM_SONG_NUM 0 // Use song slot 0
#define ICE_CREAM_SONG_LEN 10 // Number of notes in the song

// Note Numbers (MIDI Standard)
#define NOTE_G5 79
#define NOTE_E5 76
#define NOTE_C5 72
#define NOTE_G4 67
// Durations (in 1/64ths of a second)
#define DURATION_QUARTER 16
#define DURATION_EIGHTH 8


void setup_ice_cream_jingle() {
    // Define the notes and durations arrays
    unsigned char notes[ICE_CREAM_SONG_LEN] = {
        NOTE_G5, NOTE_E5, NOTE_C5, NOTE_G4,
        NOTE_G5, NOTE_E5, NOTE_G5, NOTE_E5,
        NOTE_C5, NOTE_G4
    };
    unsigned char durations[ICE_CREAM_SONG_LEN] = {
        DURATION_QUARTER, DURATION_QUARTER, DURATION_QUARTER, DURATION_QUARTER,
        DURATION_EIGHTH, DURATION_EIGHTH, DURATION_EIGHTH, DURATION_EIGHTH,
        DURATION_QUARTER, DURATION_QUARTER
    };

    // Load the song into the Roomba
    oi_loadSong(ICE_CREAM_SONG_NUM, ICE_CREAM_SONG_LEN, notes, durations);

    // Short delay recommended after sending commands
    timer_waitMillis(100);
}


void trigger_ice_cream_jingle() {
    oi_play_song(ICE_CREAM_SONG_NUM);

}
