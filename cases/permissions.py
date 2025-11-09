from .models import AccesoCaso, Caso

def is_admin(user):
    return user.is_superuser or getattr(user, "is_staff", False)

def puede_ver_caso(user, caso: Caso):
    if is_admin(user):
        return True
    if caso.abogado_responsable == user:
        return True
    return AccesoCaso.objects.filter(caso=caso, abogado=user).exists()

def puede_subir_caso(user, caso: Caso):
    if is_admin(user):
        return True
    if caso.abogado_responsable == user:
        return True
    return AccesoCaso.objects.filter(caso=caso, abogado=user, puede_editar=True).exists()
