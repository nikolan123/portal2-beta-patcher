// Caption replacement for the Aquarium core in p2_lab_slowfield_1 and the following p2_lab_hub_2 (852_0)
//
// The game picks these voice lines at random but gives them all the same
// subtitle. The original group is muted, and this script plays each line by
// its own name so the correct subtitle appears.

::AquariumCore <- null
::AquariumHeld <- false
::AquariumActive <- false
::AquariumNextLine <- 0.0
::AquariumPainReady <- 0.0

::AquariumHeldLines <- [
    { event = "sphere02.AQUARIUM01", duration = 0.768 },
    { event = "sphere02.AQUARIUM02", duration = 0.511 },
    { event = "sphere02.AQUARIUM03", duration = 0.511 },
    { event = "sphere02.AQUARIUM04", duration = 0.591 },
    { event = "sphere02.AQUARIUM05", duration = 0.491 },
    { event = "sphere02.AQUARIUM07", duration = 0.465 },
    { event = "sphere02.AQUARIUM08", duration = 1.496 },
    { event = "sphere02.AQUARIUM09", duration = 1.197 },
    { event = "sphere02.AQUARIUM10", duration = 1.602 },
    { event = "sphere02.AQUARIUM11", duration = 0.397 },
    { event = "sphere02.AQUARIUM12", duration = 0.498 },
    { event = "sphere02.AQUARIUM13", duration = 1.562 },
    { event = "sphere02.AQUARIUM14", duration = 0.556 },
    { event = "sphere02.AQUARIUM15", duration = 0.473 },
    { event = "sphere02.AQUARIUM16", duration = 1.122 },
    { event = "sphere02.AQUARIUM17", duration = 2.148 }
]

::AquariumLooseLines <- [
    { event = "sphere02.WANNAGO01", duration = 0.556 },
    { event = "sphere02.ATTENTION01", duration = 0.389 },
    { event = "sphere02.ATTENTION02", duration = 0.627 },
    { event = "sphere02.WANNAGO02", duration = 0.473 },
    { event = "sphere02.ATTENTION03", duration = 2.148 },
    { event = "sphere02.WANNAGO03", duration = 1.122 },
    { event = "sphere02.ATTENTION04", duration = 0.280 },
    { event = "sphere02.ATTENTION05", duration = 0.597 },
    { event = "sphere02.ATTENTION06", duration = 0.570 }
]

::AquariumPainLines <- [
    { event = "sphere02.GRUNTS01", duration = 0.139 },
    { event = "sphere02.GRUNTS02", duration = 0.311 },
    { event = "sphere02.GRUNTS03", duration = 0.185 }
]

function AquariumPick(lines)
{
    return lines[RandomInt(0, lines.len() - 1)]
}

function AquariumPlay(line)
{
    if (AquariumCore != null)
        AquariumCore.EmitSound(line.event)
}

function AquariumOnPickup()
{
    AquariumHeld = true
    AquariumActive = true
    AquariumNextLine = Time() + 0.05
}

function AquariumOnDrop()
{
    AquariumHeld = false
    AquariumActive = true
    AquariumNextLine = Time() + 0.05
}

function AquariumOnPain()
{
    if (AquariumCore == null || Time() < AquariumPainReady)
        return

    local line = AquariumPick(AquariumPainLines)
    AquariumPlay(line)
    AquariumPainReady = Time() + line.duration + 0.35
    AquariumNextLine = AquariumPainReady + 0.25
}

function AquariumThink()
{
    if (AquariumCore == null)
        return

    if (AquariumActive && Time() >= AquariumNextLine)
    {
        local line = AquariumPick(AquariumHeld ? AquariumHeldLines : AquariumLooseLines)
        AquariumPlay(line)
        AquariumNextLine = Time() + line.duration + 0.50
    }

    EntFire("worldspawn", "CallScriptFunction", "AquariumThink", 0.10)
}

function AquariumSetup()
{
    AquariumCore = Entities.FindByName(null, "brain_core_sphere_0")
    if (AquariumCore == null)
    {
        printl("Aquarium subtitle fix: brain_core_sphere_0 was not found")
        return
    }

    AquariumCore.ValidateScriptScope()
    local scope = AquariumCore.GetScriptScope()
    // These callbacks run in the sphere's script scope, not worldspawn's.
    // Update root-table state directly so they survive that scope boundary.
    scope.AquariumPickedUp <- function()
    {
        ::AquariumHeld = true
        ::AquariumActive = true
        ::AquariumNextLine = Time() + 0.05
    }
    scope.AquariumDropped <- function()
    {
        ::AquariumHeld = false
        ::AquariumActive = true
        ::AquariumNextLine = Time() + 0.05
    }
    scope.AquariumHurt <- function()
    {
        EntFire("worldspawn", "CallScriptFunction", "AquariumOnPain", 0.0)
    }

    AquariumCore.ConnectOutput("OnPlayerPickup", "AquariumPickedUp")
    AquariumCore.ConnectOutput("OnPhysGunPickup", "AquariumPickedUp")
    AquariumCore.ConnectOutput("OnPhysGunDrop", "AquariumDropped")
    AquariumCore.ConnectOutput("OnDamaged", "AquariumHurt")
    AquariumCore.ConnectOutput("OnPhysGunPunt", "AquariumHurt")

    // The player enters hub_2 already holding this core, so there is no new
    // pickup output to start its held chatter.
    if (GetMapName() == "p2_lab_hub_2")
    {
        AquariumHeld = true
        AquariumActive = true
        AquariumNextLine = Time() + 0.05
    }

    // The map already has player-only trigger_once volumes surrounding this
    // mounted core. Use those instead of an invented distance threshold so
    // closed captions do not reveal its chatter from the start of the map.
    local nearbyTrigger = null
    while ((nearbyTrigger = Entities.FindByClassname(nearbyTrigger, "trigger_once")) != null)
    {
        local delta = nearbyTrigger.GetOrigin() - AquariumCore.GetOrigin()
        local distanceSquared = (delta.x * delta.x) + (delta.y * delta.y) +
            (delta.z * delta.z)
        if (distanceSquared <= (128 * 128))
        {
            nearbyTrigger.ValidateScriptScope()
            local triggerScope = nearbyTrigger.GetScriptScope()
            triggerScope.AquariumPlayerArrived <- function()
            {
                ::AquariumActive = true
                ::AquariumNextLine = Time() + 0.05
            }
            nearbyTrigger.ConnectOutput("OnStartTouch", "AquariumPlayerArrived")
        }
    }

    printl("Aquarium subtitle fix: active")
    AquariumThink()
}

AquariumSetup()
