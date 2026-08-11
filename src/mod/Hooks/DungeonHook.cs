using System.Collections.Generic;
using Amplitude.Unity.Framework;
using DotEAgent.Models;

namespace DotEAgent.Hooks
{
    /// <summary>
    /// Extracts dungeon-level state: room graph, power states, doors, crystal status.
    /// </summary>
    public class DungeonHook : IStateHook
    {
        private Dungeon dungeon;
        private Dictionary<Room, int> roomIndexCache;

        public string HookId { get { return "dungeon"; } }
        public bool IsBound { get { return dungeon != null; } }

        public bool TryBind()
        {
            dungeon = SingletonManager.Get<Dungeon>(false);
            return dungeon != null;
        }

        public object ExtractState()
        {
            if (dungeon == null)
                return null;

            List<Room> openedRooms = dungeon.OpenedRooms;
            if (openedRooms == null || openedRooms.Count == 0)
                return null;

            // Build room index lookup (Room -> index in our list)
            roomIndexCache = new Dictionary<Room, int>();
            for (int i = 0; i < openedRooms.Count; i++)
            {
                roomIndexCache[openedRooms[i]] = i;
            }

            var state = new DungeonStateData();
            state.Turn = dungeon.Turn;
            state.Floor = dungeon.Level;
            state.GamePhase = dungeon.CurrentGamePhase.ToString();
            state.CrystalState = dungeon.CurrentCrystalState.ToString();
            state.DustStock = dungeon.DustStock;
            state.MaxDust = dungeon.GetMaxDustStock();
            state.ExitRoomIndex = GetRoomIndex(dungeon.ExitRoom);
            state.StartRoomIndex = GetRoomIndex(dungeon.StartRoom);

            // Extract room states
            state.Rooms = new List<RoomStateData>(openedRooms.Count);
            for (int i = 0; i < openedRooms.Count; i++)
            {
                state.Rooms.Add(ExtractRoomState(openedRooms[i], i));
            }

            // Extract closed doors
            state.ClosedDoors = ExtractClosedDoors();

            return state;
        }

        /// <summary>
        /// Gets our room index for a given Room reference. Returns -1 if not found.
        /// </summary>
        public int GetRoomIndex(Room room)
        {
            if (room == null || roomIndexCache == null)
                return -1;
            int index;
            if (roomIndexCache.TryGetValue(room, out index))
                return index;
            return -1;
        }

        /// <summary>
        /// Provides external access to the room index cache (for other hooks that need room IDs).
        /// </summary>
        public Dictionary<Room, int> GetRoomIndexCache()
        {
            return roomIndexCache;
        }

        private RoomStateData ExtractRoomState(Room room, int index)
        {
            var data = new RoomStateData();
            data.Index = index;
            data.IsPowered = room.IsPowered;
            data.IsAutoPowered = room.IsAutoPowered || room.IsAutoPoweredByEvent;
            data.IsExitRoom = room.IsExitRoom;
            data.IsStartRoom = room.IsStartRoom;
            data.IsFullyOpened = room.IsFullyOpened;
            data.Depth = room.Depth;
            data.SuffersEMP = room.SuffersEMP;
            data.EmpTurnsRemaining = room.EmpTurnsRemaining;
            data.DustLootAmount = room.DustLootAmount;

            // Artifact and Stele detection (both occupy the major module slot)
            data.HasArtifact = (room.MajorModule != null && room.MajorModule is Artifact);
            data.HasStele = (room.MajorModule != null && room.MajorModule is Stele);

            // Adjacent rooms (only those we've opened/indexed)
            data.AdjacentRoomIndices = new List<int>();
            if (room.AdjacentRooms != null)
            {
                for (int i = 0; i < room.AdjacentRooms.Count; i++)
                {
                    int adjIndex = GetRoomIndex(room.AdjacentRooms[i]);
                    if (adjIndex >= 0)
                    {
                        data.AdjacentRoomIndices.Add(adjIndex);
                    }
                }
            }

            // Major module
            if (room.MajorModule != null && room.HasNormalMajorModule)
            {
                data.MajorModuleName = room.MajorModule.name;
            }

            // Minor modules
            data.MinorModuleNames = new List<string>();
            if (room.MinorModules != null)
            {
                for (int i = 0; i < room.MinorModules.Count; i++)
                {
                    data.MinorModuleNames.Add(room.MinorModules[i].name);
                }
            }

            // Slot counts
            data.MinorSlotCount = (room.MinorModuleSlots != null) ? room.MinorModuleSlots.Count : 0;

            // Unit counts
            data.HeroCount = (room.Heroes != null) ? room.Heroes.Count : 0;
            data.MobCount = (room.Mobs != null) ? room.Mobs.Count : 0;
            data.NpcCount = (room.NPCs != null) ? room.NPCs.Count : 0;

            return data;
        }

        private List<DoorStateData> ExtractClosedDoors()
        {
            var doors = new List<DoorStateData>();
            List<Door> openable = Door.OpenableDoors;
            if (openable == null)
                return doors;

            for (int i = 0; i < openable.Count; i++)
            {
                Door door = openable[i];
                if (door == null)
                    continue;

                int room1Idx = GetRoomIndex(door.Room1);
                int room2Idx = GetRoomIndex(door.Room2);

                // Only include doors where at least one side is a room we know about
                if (room1Idx >= 0 || room2Idx >= 0)
                {
                    var doorData = new DoorStateData();
                    doorData.Room1Index = room1Idx;
                    doorData.Room2Index = room2Idx;
                    doorData.IsOpening = door.IsOpening;
                    doors.Add(doorData);
                }
            }

            return doors;
        }
    }
}
