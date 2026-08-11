using System.Collections.Generic;

namespace DotEAgent.Models
{
    /// <summary>
    /// Serializable dungeon-level state extracted by DungeonHook.
    /// </summary>
    public class DungeonStateData
    {
        public int Turn;
        public int Floor;
        public string GamePhase;       // "Strategy" or "Action"
        public string CrystalState;    // "Plugged", "Unplugged", "PluggedOnExitSlot"
        public float DustStock;
        public float MaxDust;
        public int ExitRoomIndex;
        public int StartRoomIndex;
        public List<RoomStateData> Rooms;
        public List<DoorStateData> ClosedDoors;
    }

    /// <summary>
    /// State of a single room.
    /// </summary>
    public class RoomStateData
    {
        public int Index;               // Index in the OpenedRooms list (our room ID)
        public bool IsPowered;
        public bool IsAutoPowered;
        public bool IsExitRoom;
        public bool IsStartRoom;
        public bool IsFullyOpened;
        public int Depth;
        public bool SuffersEMP;
        public int EmpTurnsRemaining;
        public int DustLootAmount;
        public bool HasArtifact;          // Artifact present (research target, can be destroyed by enemies)
        public bool HasStele;             // Stele present (temporary effect, occupies major slot)
        public List<int> AdjacentRoomIndices;
        public string MajorModuleName;  // null if no major module
        public List<string> MinorModuleNames;
        public int MinorSlotCount;
        public int HeroCount;
        public int MobCount;
        public int NpcCount;
    }

    /// <summary>
    /// A door that is still closed (openable) between two rooms.
    /// </summary>
    public class DoorStateData
    {
        public int Room1Index;
        public int Room2Index;
        public bool IsOpening;          // Currently in opening animation
    }
}
