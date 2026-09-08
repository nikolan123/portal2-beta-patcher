// This map plays three Curiosity Core lines as raw audio files, which prevents
// their subtitles from appearing. Point those sounds at their existing named
// events so the matching Portal 1 captions are used.

function SetCuriositySound(entityName, soundName)
{
    local sound = Entities.FindByName(null, entityName)
    if (sound != null)
        sound.__KeyValueFromString("message", soundName)
}

SetCuriositySound("whats_wrong_with_your_legs_wav", "Portal.Glados_core.Curiosity_8")
SetCuriositySound("is_that_a_gun_wav", "Portal.Glados_core.Curiosity_13")
SetCuriositySound("where_are_we_going_wav", "Portal.Glados_core.Curiosity_16")

printl("Curiosity Core subtitle fix active")
