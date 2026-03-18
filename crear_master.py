# Ruta: crear_master.py
import mysql.connector
from werkzeug.security import generate_password_hash

def sembrar_master():
    print("Iniciando la creacion del Super Admin (Master)...")
    
    # 1. LLENA TUS DATOS AQUI
    mi_correo = "jempo1103@gmail.com"
    mi_password = "Jempo0302" 
    mi_nombre_completo = "Juanes Montenegro"
    
    # Encriptamos la contrasena para que Flask la entienda
    clave_hasheada = generate_password_hash(mi_password)
    
    try:
        # Conexion a tu XAMPP
        conn = mysql.connector.connect(
            host='localhost',
            database='jempos',
            user='root',
            password=''
        )
        cursor = conn.cursor()
        
        # 2. Creamos tu "Tienda Base" usando el nombre correcto de la columna: nombre_negocio
        cursor.execute(
            "INSERT INTO tiendas (nombre_negocio, estado_suscripcion) VALUES (%s, %s)", 
            ('jemPOS Central', 'activa')
        )
        
        # Capturamos el ID de la tienda que se acaba de crear
        id_de_mi_tienda = cursor.lastrowid
        
        # 3. Insertamos tu usuario respetando exactamente tus columnas y el ENUM 'Master'
        sql_usuario = """
            INSERT INTO usuarios 
            (id_tienda, nombre_completo, correo, clave_hash, rol) 
            VALUES (%s, %s, %s, %s, %s)
        """
        valores = (id_de_mi_tienda, mi_nombre_completo, mi_correo, clave_hasheada, 'Master')
        
        cursor.execute(sql_usuario, valores)
        
        conn.commit()
        print(f"¡Exito total! Usuario Master creado. Ya puedes iniciar sesion en jemPOS con el correo: {mi_correo}")
        
    except Exception as e:
        print(f"Ocurrio un error: {e}")
    finally:
        if 'cursor' in locals(): cursor.close()
        if 'conn' in locals() and conn.is_connected(): conn.close()

if __name__ == "__main__":
    sembrar_master()