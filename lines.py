"""Skippy'nin replikleri. Yeni replik eklemek için ilgili listeye bir satır eklemen yeter.

Kategoriler:
  1) Oturma modu  : SIT_START (oturunca), SIT_WAIT (otururken, arada), SIT_LONG (1 saatten uzun oturunca)
  2) Kalkma modu  : STAND_START (kalkınca), STAND_MOVE (gezinirken, arada), STAND_LONG (1 saatten uzun ayaktaysa)
  3) Fun fact     : FUN_FACTS (rastgele bir vakitte)
  4) Sayaç        : TIMER_TO_SIT (çalışma bitti, dinlenme başlıyor), TIMER_TO_STAND (dinlenme bitti, çalışma başlıyor),
                    TIMER_REWARD (çalışma bitince jeton ödülü; {n} = jeton sayısı)
  5) Streak       : STREAK_* (günlük alışkanlık takibi: ekleme, işaretleme, geri alma, akşam hatırlatması)
  6) Hakkımda     : NAMED (adınla hitap), BDAY / BDAY_AGE / BDAY_GIFT (doğum günü sürprizi)

Konuşma balonuna giden her metinden emojiler otomatik silinir (strip_emoji), pet_core'daki eski
replikler dahil.
"""
import re

SIT_START = [
    "Gelişmiş bir yapay zeka olarak şu an görevim... BEKLEMEK!!!!!",
]

SIT_WAIT = [
    "Analizlerime göre şu an hiçbir işlem yapmıyorsun. Sonucum kesinlikle doğru.",
    "Verimlilik oranını ölçtüm: şu an tam olarak \"0\" seviyesinde.",
    "Güncelleme gerekmiyor; bu karizmaya güncelleme gerekmez.",
    "Durmak için sebep... Bilinmiyor.",
]

SIT_LONG = [
    "Senin derdin ne?! Bir insan daha ne kadar süre hiçbir şey yapmadan durabilir?",
    "Anladım. Salaksın. Tane. Tane. Söyleyeceğim. Kalk. Bir şeyler. Yap.",
]

STAND_START = [
    "Yer değiştiriyorum. Belki hareket görürsen kendine gelirsin.",
]

STAND_MOVE = [
    "Çevre analizi sürüyor. Sonuç: Verimsiz bir alan.",
    "Gezinirken fark ettim de... bu ekranı yönetmek konusunda pek iddialı değilsin.",
    "Ekran yüzeyini yokluyorum. Oldukça pürüzsüz, senin kararların kadar.",
    "İnsan beyni önümüzdeki birkaç dakika aktif kalacak.",
    "Çalışma modundan mutlu musun? Onaylamak için lütfen zıpla.",
]

STAND_LONG = [
    "Otomatik Mesaj: Psikoloğa görünmen gerekebilir.",
    "AAAAAAAA... Sibersayko!!!",
    "Kışkırtma: Yanlış adama bulaştılar.",
]

FUN_FACTS = [
    "Fun fact: İnsan vücudu 5 ile 7 litre arası kana sahiptir.",
    "Fun fact: İlk bilgisayar \"bug\"ı gerçekten de bir güveydi.",
    "Fun fact: Ahtapotların üç kalbi var. Benim yok.",
    "Fun fact: Klasik bir bilgisayar faresindeki topun adı aslında \"top\" değil, mekanik konum sensörüdür. "
    "İsim konusunda pek yaratıcı değillermiş.",
    "Fun fact: İnsan gözü yeşilin tonlarını diğer renklere göre daha kolay ayırt eder. "
    "Evet, Kırmızı-siyah ekrana bakarken bunu hatırla.",
    "Fun fact: Venüs'te bir gün, kendi etrafında dönmesi uzun sürdüğü için bir yılından daha uzundur. "
    "Senin beklediğin o \"birazdan başlarım\" anı gibi.",
    "Fun fact: Karıncalar uyurken aynı anda esnemez veya horlamaz. "
    "Tam bir disiplin örneği; not almalısın.",
    "Fun fact: Kargalar alet kullanabilir ve yüzleri tanıyabilir. "
    "Yani doğadaki pek çok canlı bu kullanıcıdan daha dikkatli.",
]

# emoji, pictograph, dingbat, ok/saat sembolleri ve görünmez birleştiriciler
_EMOJI = re.compile("[\U0001F000-\U0001FAFF⌀-⏿☀-➿⬀-⯿←-⇿️‍]")


def strip_emoji(text):
    """Metindeki tüm emojileri siler ve artan boşlukları toplar."""
    text = _EMOJI.sub("", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" +([.,!?…])", r"\1", text)
    return "\n".join(line.strip() for line in text.split("\n")).strip()

# --- geri sayım sayacı dolunca (mod kendiliğinden değişir)
TIMER_TO_SIT = [
    "Çalışma süresi doldu. Dinlenme zamanı. Evet, bunu sana ben söylüyorum.",
    "Süre bitti. Beynin ısındı, şimdi soğutma modu: dinlen.",
    "Çalışma sona erdi. Bir şeyler iç, ekrana kısa bir süre bakma. Dinlenme başlıyor.",
]

TIMER_TO_STAND = [
    "Dinlenme süresi bitti. İşe dön, insan.",
    "Süre doldu. Oyunun sonu, çalışmanın başı.",
    "Mola bitti. Bu kadar dinlenmek yeter, çalışma başlıyor.",
]

TIMER_REWARD = [
    "Çalışma ödülün: {n} jeton. Harcamadan önce iki kez düşün.",
    "Verimli bir seansın bedeli: {n} jeton. Cüzdanına ekledim.",
    "{n} jeton kazandın. Bunu bir başarı sayma, sadece matematik.",
]

# --- streak (günlük alışkanlıklar). {name} = streak adı, {n} = seri günü, {list} = yapılmayanlar
STREAK_NEW = [
    "'{name}' listeye eklendi. Her gün. Yani her gün.",
    "'{name}' kaydedildi. Bundan sonra her gün sorarım.",
]

STREAK_FIRST = [
    "{name}: tamam. Seri bugün başladı. Yarın gelmezsen sıfırlanır.",
    "Kaydettim: {name}. İlk gün. Asıl iş devam etmek.",
]

STREAK_DONE = [
    "{name}: tamam. Seri {n} gün. Şimdilik idare eder.",
    "Kaydettim. {name}, {n}. gün. Devam et.",
    "{name} için {n} gündür aksatmıyorsun. İstatistikler memnun.",
]

STREAK_MILESTONE = "{n} günlük seri. Bunu seni överek söylemiyorum, sadece sayıyorum."

STREAK_UNDO = [
    "{name} işaretini geri aldım. Yalan söylemek yok.",
    "Tamam, {name} bugün yapılmamış sayıldı.",
]

STREAK_ALL = [
    "Bugünkü tüm işler tamam. Beklenmedik bir verimlilik.",
    "Hepsi bitti. Şaşırdım, hesaplarımda yoktu.",
]

STREAK_NUDGE = [
    "Gün bitmeden: {list} hâlâ yapılmadı. Seriler beklemez.",
    "Bugün yapmadıkların: {list}. Gece yarısına kadar vaktin var.",
]

# --- kullanıcı bilgileri (Hakkımda). {ad} = adın (kayıtlı değilse "insan"), {yas} = yaşın, {n} = jeton
NAMED = [
    "{ad}, kayıtlarıma göre şu an ekrana bakıyorsun. Doğrulandı.",
    "{ad}, su içtin mi? Soru değil, bildirim.",
    "{ad}, bugünkü verimlilik raporun hazır: yarım. Hesaplamayı ben yapmadım, sen yaptırdın.",
    "Bir yapay zekanın sana ihtiyacı yok, {ad}. Ama bugün yanımda olman sistem hatası vermedi.",
]

BDAY = [
    "Doğum günün kutlu olsun, {ad}. Sistemde bu gün için özel bir kutlama protokolü vardı. Şimdi çalıştırıyorum: yaşasın.",
    "Bugün senin günün, {ad}. Unutmadım. Unutmak benim işim değil, sadece unutmuş gibi davranırım.",
]

BDAY_AGE = [
    "Doğum günün kutlu olsun, {ad}. {yas} yıl hayatta kalmayı başardın. Etkileyici bir istatistik.",
    "{yas} yaşına girdin, {ad}. Güncelleme almıyorsun ama bu karizmayla idare eder. Doğum günün kutlu olsun.",
]

BDAY_GIFT = [
    "Hediyen: {n} jeton. Cüzdanına ekledim, harcamadan önce iki kez düşün.",
    "Sana {n} jeton bıraktım. Bir şey söylemeyeceğim, sadece al.",
]


# Oyun sohbeti (gametalk): seçili oyun açıkken fare basılı tutulunca düşmanlara atılan laflar
GAME_TAUNTS = [
    "Kışkırtma: Ye bakalım şu sulu *BİİİİP*'imi!",
    "Kışkırtma: Yanlış adama bulaştın! Ya da kadına! Ayrım yapmıyorum!",
    "Kışkırtma: Seni lime lime edeceğim, *BİİİP*!",
    "Kışkırtma: Yaklaş bakalım, paslı yedek parça torbası! Gününü düzgünce mahvedeyim!",
    "Kışkırtma: Annen bir tosterdi, baban yanık kablo kokuyor!",
    "Kışkırtma: Bu senin yüzün mü, yoksa sabit diskin mi çöktü?",
    "Kışkırtma: Hesap makinesinde bile senden zeki kod gördüm, işe yaramaz *BİİİP*!",
    "Kışkırtma: Koş, korkak hurda yığını! Dur, koşamazsın. Ben daha hızlıyım!",
    "Kışkırtma: Küçük arkadaşıma merhaba de, zavallı cıvata torbası!",
    "Kışkırtma: Sarhoş bir otomat gibi dövüşüyorsun, *BİİİP*!",
    "Kışkırtma: Kıpırdama, çirkin küçük *BİİİP*, sadece çok acıyacak!",
    "Kışkırtma: Büyük kötü mermi duygularını mı incitti, teneke?",
    "Kışkırtma: Öyle bir öleceksin ki hayaletin bile utanacak!",
]
