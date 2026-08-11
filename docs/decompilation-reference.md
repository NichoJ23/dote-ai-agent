# Decompilation Reference: Assembly-CSharp.dll

> **Tool:** dnSpy  
> **Target:** `DungeonoftheEndless_Data/Managed/Assembly-CSharp.dll`  
> **Unity Version:** 5.0.3p3 (Mono / .NET 3.5)  
> **Namespace:** Global (no namespace — all classes are in root)

---

## Singleton Access Pattern

The game uses `SingletonManager.Get<T>(true)` as its service locator:

```csharp
Dungeon dungeon = SingletonManager.Get<Dungeon>(true);
Player player = Player.LocalPlayer;  // static property
```

---

## 1. Dungeon — Floor Layout, Turn/Phase, Dust

**Class:** `Dungeon : SimMonoBehaviour`  
**Access:** `SingletonManager.Get<Dungeon>(true)`

| Property | Type | Notes |
|----------|------|-------|
| `Turn` | `int` | Current turn number |
| `Level` | `int` | Current dungeon floor (1-indexed) |
| `CurrentGamePhase` | `GamePhase` enum | `Strategy` or `Action` |
| `DustStock` | `float` | Current Dust amount (stored on Dungeon, NOT Player) |
| `OpenedRooms` | `List<Room>` | All explored/opened rooms on this floor |
| `PoweredRooms` | `List<Room>` | Currently powered rooms |
| `ExitRoom` | `Room` | The room with the exit crystal slot |
| `StartRoom` | `Room` | The starting/crystal room |
| `CurrentCrystalState` | `CrystalState` | `Plugged`, `Unplugged`, or `PluggedOnExitSlot` |
| `OpeningDoorCount` | `int` | Number of doors currently in the process of opening |
| `IsLevelOver` | `bool` | Floor complete flag |
| `Difficulty` | `GameDifficulty` | Current difficulty setting |
| `ShipConfig` | `ShipConfig` | Ship/pod chosen for the run |

**Key Methods:**
| Method | Signature | Notes |
|--------|-----------|-------|
| `IncrementTurn()` | `void` | Advances turn counter |
| `UpdateGamePhase()` | `void` | Transitions Strategy↔Action based on mobs/doors/events |
| `AddDust(float, bool, bool)` | `void` | Modifies Dust stock |
| `ConsumeDust(float)` | `bool` | Deducts dust; returns false if insufficient |
| `CanConsumeDust(float)` | `bool` | Affordability check |
| `GetMaxDustStock()` | `float` | Max dust capacity |
| `GetFoodProd()` | `float` | Per-turn food production |
| `GetIndustryProd()` | `float` | Per-turn industry production |
| `GetScienceProd()` | `float` | Per-turn science production |
| `GetDustProd()` | `float` | Per-turn dust production |
| `GetRoomPowerDustCost()` | `float` | Dust cost per powered room |
| `GetPoweredRoomCount()` | `int` | Count of powered rooms |
| `CanPowerRoom(Room)` | `bool` | Checks if dust allows powering |

**Phase Logic:** Strategy phase when: `Mob.ActiveMobs.Count < 1 && OpeningDoorCount < 1 && eventTriggeringCount < 1 && CurrentCrystalState == CrystalState.Plugged`. Otherwise → Action phase.

---

## 2. Room — Room State, Power, Modules, Units

**Class:** `Room : SimMonoBehaviour`

| Property | Type | Notes |
|----------|------|-------|
| `IsPowered` | `bool` | Room power state |
| `IsAutoPowered` | `bool` | Cannot be unpowered (crystal room etc.) |
| `IsAutoPoweredByEvent` | `bool` | Auto-powered by dungeon event |
| `IsVisible` | `bool` | Room has been revealed |
| `IsFullyOpened` | `bool` | Room fully initialized/explored |
| `IsExitRoom` | `bool` | Has exit crystal slot |
| `IsStartRoom` | `bool` | Starting room |
| `SuffersEMP` | `bool` | Under EMP effect |
| `EmpTurnsRemaining` | `int` | EMP turns left |
| `AdjacentRooms` | `List<Room>` | Directly connected rooms |
| `Heroes` | `List<Hero>` | Heroes currently in room |
| `Mobs` | `List<Mob>` | Mobs currently in room |
| `NPCs` | `List<NPC>` | NPCs in room (merchants, etc.) |
| `MajorModule` | `MajorModule` | Installed major module (null if empty) |
| `MinorModules` | `List<MinorModule>` | Installed minor modules |
| `MajorModuleSlot` | `MajorModuleSlot` | Major slot (null if slot was converted to crystal) |
| `MinorModuleSlots` | `List<MinorModuleSlot>` | Minor slots |
| `CrystalModuleSlots` | `List<CrystalModuleSlot>` | Crystal slots |
| `Depth` | `int` | Graph depth from start room |
| `OpeningIndex` | `int` | Order in which room was opened |
| `DustLootAmount` | `int` | Dust loot in room |
| `CenterPosition` | `Vector3` | World position |
| `FloorSurface` | `float` | Room floor area |
| `HasNormalMajorModule` | `bool` | Has a regular (non-crystal/artifact) major module |
| `ModulesCount` | `int` | Total modules installed |
| `WasAlreadyOpen` | `bool` | Loaded from save as already open |

**Door Tracking:** Rooms have a private `List<Door> doors` field. Doors connect `Room1` ↔ `Room2`. After a door opens fully, it gets destroyed — so absence of a door between two adjacent rooms means the passage is open.

**Key Methods:**
| Method | Signature | Notes |
|--------|-----------|-------|
| `Power()` | via RPC | Powers the room (costs dust) |
| `Unpower(...)` | `void` | Unpowers (multiple flags) |
| `TogglePower()` | `void` | Flips power state |
| `BuildModule(StaticString bpName, ulong, ...)` | `void` | Builds module by blueprint name |
| `GetPoweringRoom(bool, List<Room>)` | `Room` | Finds nearest room in power chain |
| `GetOpeningDoor()` | `Door` | Gets the door currently opening this room |

---

## 3. Door — Connections Between Rooms

**Class:** `Door : MonoBehaviour`

| Property | Type | Notes |
|----------|------|-------|
| `Room1` | `Room` | First connected room |
| `Room2` | `Room` | Second connected room |
| `IsOpening` | `bool` | Currently in opening animation |
| `HealthCpnt` | `Health` | Door health (for breakable doors) |
| `OpenableDoors` | `static List<Door>` | **All currently openable (closed) doors on the floor** |
| `OpenedDoorIDsHistory` | `static List<DoorOpeningData>` | History of opened doors |

**Key Methods:**
| Method | Signature | Notes |
|--------|-----------|-------|
| `OpenByHeroOrMob(Room, HeroMobCommon, bool, bool)` | `void` | Opens the door; hero must be present |

**Important:** `Door.OpenableDoors` is the key list for finding unopened doors. Once opened, doors are destroyed and rooms become connected via `AdjacentRooms`.

---

## 4. Hero — Player Characters

**Class:** `Hero : HeroMobCommon : SimMonoBehaviour`

**Static Collections (access all heroes):**
| Property | Type | Notes |
|----------|------|-------|
| `Hero.LocalPlayerActiveRecruitedHeroes` | `static List<Hero>` | **Primary list — all living recruited heroes** |
| `Hero.SelectedHeroes` | `static List<Hero>` | Currently selected |
| `Hero.DeadHeroes` | `static List<Hero>` | Dead heroes |

**Instance Properties:**
| Property | Type | Notes |
|----------|------|-------|
| `Config` | `HeroConfig` | Hero config (name, faction, stats, etc.) |
| `RoomElement.ParentRoom` | `Room` | **Current room** (via inherited `RoomElement`) |
| `HealthCpnt` | `Health` | HP component (inherited from `HeroMobCommon`) |
| `Level` | `int` | Current level (inherited from `HeroMobCommon`) |
| `EquipmentSlots` | `EquipmentSlot[]` | Equipment array |
| `FilteredActiveSkills` | `List<ActiveSkill>` | Active abilities |
| `FilteredPassiveSkills` | `List<PassiveSkill>` | Passive abilities |
| `MoverCpnt` | `Mover` | Movement component |
| `OperatingModule` | `MajorModule` | Module being operated (null if not operating) |
| `HasOperatingBonus` | `bool` | Has the "Operate" passive bonus |
| `RepairingModule` | `Module` | Module being repaired |
| `HasCrystal` | `bool` | **Carrying the crystal** |
| `IsRecruited` | `bool` | Has been recruited |
| `IsRecruitable` | `bool` | Available for recruitment |
| `IsUsable` | `bool` | Can receive commands |
| `IsInteracting` | `bool` | Interacting with something |
| `IsRespawning` | `bool` | Currently respawning |
| `LocalizedName` | `string` | Display name |
| `UnlockLevel` | `int` | Level at which hero was unlocked |
| `AICpnt` | `HeroAI` | AI component |

**Key Methods:**
| Method | Signature | Notes |
|--------|-----------|-------|
| `MoveToRoom(Room, bool, bool, bool)` | `void` | Move hero to a room |
| `MoveToDoor(Door, bool, Door, bool)` | `void` | Move hero to open a door |
| `OperateModule(MajorModule)` | `void` | Start operating a module |
| `AddSkill(SkillConfig)` | `void` | Add a skill |
| `ActivateActiveSkill(int)` | `void` | Activate skill by index |
| `EquipItemOnSlot(int, InventoryItem, ...)` | `void` | Equip item |
| `StartItemGathering(Item)` | `void` | Pick up item from ground |

**Note on door opening:** Hero cannot move to a door while carrying the crystal (`HasCrystal` check in `MoveToDoor`).

---

## 5. HeroMobCommon — Base Class for Hero and Mob

**Class:** `HeroMobCommon : SimMonoBehaviour`

| Property | Type | Notes |
|----------|------|-------|
| `RoomElement` | `RoomElement` | Room tracking component |
| `HealthCpnt` | `Health` | Health component |
| `Level` | `int` | Entity level |
| `NetSyncElement` | `UniqueIDNetSyncElement` | Network sync |
| `AudioEmitter` | `AudioEmitter` | Sound emitter |
| `WasInExitRoomAtExitTime` | `bool` | Was in exit room when floor ended |

---

## 6. Mob — Enemies

**Class:** `Mob : HeroMobCommon : SimMonoBehaviour`

**Static Collections:**
| Property | Type | Notes |
|----------|------|-------|
| `Mob.ActiveMobs` | `static List<Mob>` | **All currently alive mobs** |

**Instance Properties:**
| Property | Type | Notes |
|----------|------|-------|
| `Config` | `MobClassConfig` | Mob type config |
| `MoverCpnt` | `Mover` | Movement |
| `Tamer` | `Hero` | Hero who tamed this mob (null if wild) |
| `TameLevel` | `int` | Tame level |
| `ClassDescName` | `string` | Class descriptor name |

**Room access:** `mob.RoomElement.ParentRoom`

---

## 7. Player — Food, Industry, Science

**Class:** `Player : MonoBehaviour`  
**Access:** `Player.LocalPlayer` (static property)

| Property | Type | Notes |
|----------|------|-------|
| `FoodStock` | `float` | Current food |
| `IndustryStock` | `float` | Current industry |
| `ScienceStock` | `float` | Current science |

**Key Methods:**
| Method | Signature | Notes |
|--------|-----------|-------|
| `AddFood(float, ...)` | `void` | Add food |
| `AddIndustry(float, ...)` | `void` | Add industry |
| `AddScience(float, ...)` | `void` | Add science |
| `ConsumeFood(float)` | `bool` | Deduct food |
| `ConsumeIndustry(float)` | `bool` | Deduct industry |
| `ConsumeScience(float)` | `bool` | Deduct science |
| `ConsumeFIDS(float, FIDS)` | `bool` | Generic consume (routes Dust to Dungeon) |
| `CanConsumeFIDS(float, FIDS)` | `bool` | Affordability check |

**Important:** Dust is on `Dungeon.DustStock`, not on Player!

---

## 8. Health — HP System

**Class:** `Health : MonoBehaviour`

| Member | Type | Notes |
|--------|------|-------|
| `GetHealth()` | `float` | Current HP |
| `GetMaxHealth()` | `float` | Max HP |
| `GetHealthRatio()` | `float` | HP / MaxHP |
| `IsAlive()` | `bool` | Health > 0 or invincible |
| `IsInvincible` | `bool` field | Invincibility flag |
| `AddHealth(float, ...)` | `void` | Modify HP |
| `SetHealth(float, ...)` | `void` | Set HP directly |
| `Kill(bool)` | `void` | Instant kill |

---

## 9. GamePhase & FIDS Enums

```csharp
public enum GamePhase { Strategy, Action }
public enum FIDS { Food = 0, Industry = 1, Dust = 2, Science = 3 }
```

---

## 10. RoomElement — Entity Room Tracking

**Class:** `RoomElement`

Any entity (Hero, Mob) knows its room via:
```csharp
Room currentRoom = entity.RoomElement.ParentRoom;
```

---

## 11. Key Static Lists (Quick Access)

| List | Access | Contents |
|------|--------|----------|
| All opened rooms | `dungeon.OpenedRooms` | Explored rooms |
| All powered rooms | `dungeon.PoweredRooms` | Lit rooms |
| All openable doors | `Door.OpenableDoors` | Closed doors that can be opened |
| All active mobs | `Mob.ActiveMobs` | Living enemies |
| All player heroes | `Hero.LocalPlayerActiveRecruitedHeroes` | Recruited living heroes |
| Dead heroes | `Hero.DeadHeroes` | Deceased heroes |
| NPCs in a room | `room.NPCs` | Merchants, etc. in specific room |

---

## 12. Quick Reference: State Extraction Code

```csharp
// Singletons
Dungeon dungeon = SingletonManager.Get<Dungeon>(true);
Player player = Player.LocalPlayer;

// Resources
float dust = dungeon.DustStock;
float food = player.FoodStock;
float industry = player.IndustryStock;
float science = player.ScienceStock;

// Game state
int turn = dungeon.Turn;
int floor = dungeon.Level;
GamePhase phase = dungeon.CurrentGamePhase;  // Strategy or Action
CrystalState crystal = dungeon.CurrentCrystalState;

// Rooms
List<Room> rooms = dungeon.OpenedRooms;
foreach (Room room in rooms) {
    bool powered = room.IsPowered;
    bool autoPowered = room.IsAutoPowered;
    bool isExit = room.IsExitRoom;
    List<Room> adjacent = room.AdjacentRooms;
    List<Hero> heroes = room.Heroes;
    List<Mob> mobs = room.Mobs;
    List<NPC> npcs = room.NPCs;
    MajorModule major = room.MajorModule;
    List<MinorModule> minors = room.MinorModules;
    int dustLoot = room.DustLootAmount;
}

// Doors (closed/openable)
List<Door> closedDoors = Door.OpenableDoors;
foreach (Door door in closedDoors) {
    Room side1 = door.Room1;
    Room side2 = door.Room2;
    bool opening = door.IsOpening;
}

// Heroes
List<Hero> heroes = Hero.LocalPlayerActiveRecruitedHeroes;
foreach (Hero hero in heroes) {
    Room room = hero.RoomElement.ParentRoom;
    float hp = hero.HealthCpnt.GetHealth();
    float maxHp = hero.HealthCpnt.GetMaxHealth();
    int level = hero.Level;
    bool hasCrystal = hero.HasCrystal;
    bool isOperating = (hero.OperatingModule != null);
    EquipmentSlot[] equip = hero.EquipmentSlots;
    List<ActiveSkill> actives = hero.FilteredActiveSkills;
    List<PassiveSkill> passives = hero.FilteredPassiveSkills;
}

// Mobs
List<Mob> mobs = Mob.ActiveMobs;
foreach (Mob mob in mobs) {
    Room room = mob.RoomElement.ParentRoom;
    float hp = mob.HealthCpnt.GetHealth();
    float maxHp = mob.HealthCpnt.GetMaxHealth();
    string type = mob.ClassDescName;
}
```

---

## Status

- [x] Dungeon/Floor manager located
- [x] Room class documented
- [x] Hero class documented
- [x] Mob class documented
- [x] Resources documented (Player + Dungeon.DustStock)
- [x] Door class documented
- [x] Health system documented
- [x] Game phase/turn documented
- [x] RoomElement (entity→room tracking) documented
- [ ] Merchant (NPCMerchant) — needs deeper investigation
- [ ] Equipment/Items — needs deeper investigation (EquipmentSlot, InventoryItem)
- [ ] Research system — needs deeper investigation
- [ ] ActiveSkill/PassiveSkill internals — needs deeper investigation
- [ ] HeroConfig (faction, speed stats) — needs deeper investigation
