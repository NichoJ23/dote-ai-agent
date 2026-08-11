using System.Collections.Generic;
using DotEAgent.Models;

namespace DotEAgent.Hooks
{
    /// <summary>
    /// Extracts mob states: type, room, HP.
    /// </summary>
    public class MobHook : IStateHook
    {
        private DungeonHook dungeonHook;

        public string HookId { get { return "mobs"; } }
        public bool IsBound { get { return dungeonHook != null && dungeonHook.IsBound; } }

        public MobHook(DungeonHook dungeonHook)
        {
            this.dungeonHook = dungeonHook;
        }

        public bool TryBind()
        {
            return dungeonHook != null && dungeonHook.IsBound;
        }

        public object ExtractState()
        {
            List<Mob> mobs = Mob.ActiveMobs;
            if (mobs == null || mobs.Count == 0)
                return new List<MobStateData>();

            var result = new List<MobStateData>(mobs.Count);
            for (int i = 0; i < mobs.Count; i++)
            {
                Mob mob = mobs[i];
                if (mob == null)
                    continue;

                var data = new MobStateData();
                data.Type = mob.ClassDescName ?? mob.name;

                if (mob.RoomElement != null && mob.RoomElement.ParentRoom != null)
                {
                    data.RoomIndex = dungeonHook.GetRoomIndex(mob.RoomElement.ParentRoom);
                }
                else
                {
                    data.RoomIndex = -1;
                }

                if (mob.HealthCpnt != null)
                {
                    data.Hp = mob.HealthCpnt.GetHealth();
                    data.MaxHp = mob.HealthCpnt.GetMaxHealth();
                }

                // What this mob targets (heroes, modules, artifacts, crystal, etc.)
                if (mob.Config != null)
                {
                    data.TargetType = mob.Config.AITargetType.ToString();
                }
                else
                {
                    data.TargetType = "Unknown";
                }

                result.Add(data);
            }

            return result;
        }
    }
}
