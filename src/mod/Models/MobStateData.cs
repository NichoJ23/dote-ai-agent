namespace DotEAgent.Models
{
    public class MobStateData
    {
        public string Type;           // Mob class descriptor name
        public int RoomIndex;
        public float Hp;
        public float MaxHp;
        public string TargetType;     // "AntiHeroMob", "AntiModuleMob", "Artifact", "Crystal", etc.
    }
}
